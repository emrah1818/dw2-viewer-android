// Adapted subset of Feerdus95/dw3-model-viewer stage.cpp; see LICENSE and CREDITS.md.
#include "stage.h"
#include <cmath>
#include <cstdio>
#include <cstring>
#include <map>
#include <set>
/* --- matrices: column-major 4x4, affine --- */

static void identity(float m[16]) {
    for (int k = 0; k < 16; k++) m[k] = k % 5 == 0;
}

static void mul(const float a[16], const float b[16], float out[16]) {
    float w[16];
    for (int c = 0; c < 4; c++)
        for (int i = 0; i < 4; i++)
            w[c * 4 + i] = a[i] * b[c * 4] + a[4 + i] * b[c * 4 + 1] + a[8 + i] * b[c * 4 + 2] + a[12 + i] * b[c * 4 + 3];
    memcpy(out, w, sizeof w);
}

static bool invert(const float m[16], float out[16]) {
    float a = m[0], b = m[4], c = m[8], d = m[1], e = m[5], f = m[9], g = m[2], h = m[6], i = m[10];
    float det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g);
    if (fabsf(det) < 1e-9f) return false;
    float r[9] = {(e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det,
                  (f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det,
                  (d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det};
    identity(out);
    for (int row = 0; row < 3; row++)
        for (int col = 0; col < 3; col++) out[col * 4 + row] = r[row * 3 + col];
    for (int row = 0; row < 3; row++) out[12 + row] = -(out[row] * m[12] + out[4 + row] * m[13] + out[8 + row] * m[14]);
    return true;
}

static std::array<float, 3> apply(const float m[16], float x, float y, float z) {
    return {m[0] * x + m[4] * y + m[8] * z + m[12], m[1] * x + m[5] * y + m[9] * z + m[13], m[2] * x + m[6] * y + m[10] * z + m[14]};
}

/* Where a bone's keys' first frame puts it, under its parents; a part
   hidden there (scaled to nothing, shown by its motion) at full size */
static void bind_world(const Model &m, int b, float out[16]) {
    if (b <= 0) return identity(out);
    const Bone &bone = m.bones[b];
    Vec3s v[3];
    for (int t = 0; t < 3; t++) v[t] = {bone.keys[t][0].x, bone.keys[t][0].y, bone.keys[t][0].z};
    if (std::abs(v[2].x) <= 48 || std::abs(v[2].y) <= 48 || std::abs(v[2].z) <= 48) v[2] = {4096, 4096, 4096};
    float local[16], parent[16];
    bone_matrix(v[0], v[1], v[2], local);
    bind_world(m, bone.parent < b ? bone.parent : 0, parent);
    mul(parent, local, out);
}

/* --- from the game's model --- */

void StageEdit::fromModel(const Model &m, const StageInfo &info) {
    parts.clear(), images.clear(), error.clear();
    memcpy(bg, info.bg, 3);
    /* an image for each texture page and CLUT the polygons read; the ones
       semi-transparent polygons read with their semi-transparent texels half
       opaque */
    std::map<std::pair<int, int>, int> byCombo;
    std::set<std::pair<int, int>> semi;
    for (const Mesh &me : m.meshes)
        for (const Poly &p : me.polys)
            if (p.textured && p.abr) semi.insert({p.tpage & 0x19F, p.clut});
    int white = -1;
    for (size_t b = 1; b < m.bones.size(); b++) {
        const Bone &bone = m.bones[b];
        const Mesh &mesh = m.meshes[bone.mesh];
        StagePart part;
        char name[32];
        snprintf(name, sizeof name, "part_%02d", (int)b);
        part.name = name;
        part.parent = bone.parent < (int)b ? bone.parent : 0;
        const uint8_t *k = m.arc.entry(bone.keyEntry);
        part.keys.assign(k, k + m.arc.entry_size(bone.keyEntry));
        bind_world(m, (int)b, part.bind);
        for (uint8_t nb : info.noBounds) {
            if (!nb) break;
            if (nb == b) part.noBounds = true;
        }
        if (!mesh.polys.empty()) memcpy(part.color, mesh.polys[0].color, 3);
        for (const Vec3s &v : mesh.verts) part.verts.push_back(apply(part.bind, v.x, v.y, v.z));
        for (const Poly &p : mesh.polys) {
            StageFace f;
            f.n = p.quad ? 4 : 3;
            f.abr = p.abr;
            /* the PSX's front is clockwise on screen: tri 0 1 2, quad 0 1 3 2 */
            static const int CCW[2][4] = {{0, 2, 1, 0}, {0, 2, 3, 1}};
            for (int c = 0; c < f.n; c++) {
                int k2 = CCW[p.quad][c];
                f.v[c] = p.idx[k2];
                f.uv[c][0] = p.uv[k2][0], f.uv[c][1] = p.uv[k2][1];
            }
            if (p.textured) {
                std::pair<int, int> key = {p.tpage & 0x19F, p.clut};
                auto it = byCombo.find(key);
                if (it == byCombo.end()) {
                    StageImage img;
                    img.tpage = key.first, img.pageClut = key.second;
                    img.w = img.h = 256;
                    img.px = decode_page(m.vram, (uint16_t)key.first, (uint16_t)key.second, 256, 256, semi.count(key) > 0);
                    if (tpage_depth((uint16_t)key.first) == 0) {
                        int px = tpage_x((uint16_t)key.first), py = tpage_y((uint16_t)key.first);
                        img.source = info.fid * 64 + (key.first & 0x1F);
                        img.index.resize(256 * 256);
                        for (int v = 0; v < 256; v++)
                            for (int u = 0; u < 256; u++)
                                img.index[v * 256 + u] = m.vram[(py + v) * 1024 + px + u / 4] >> (u & 3) * 4 & 15;
                        img.clutX = clut_x((uint16_t)key.second), img.clutY = clut_y((uint16_t)key.second);
                        for (int c = 0; c < 16; c++) img.clut[c] = m.vram[img.clutY * 1024 + img.clutX + c];
                    }
                    it = byCombo.emplace(key, (int)images.size()).first;
                    images.push_back(std::move(img));
                }
                f.image = it->second;
            } else {
                if (white < 0) {
                    white = (int)images.size();
                    images.push_back({4, 4, std::vector<uint32_t>(16, 0xFFFFFFFFu)});
                    images.back().flat = true;
                }
                f.image = white;
                for (auto &uv : f.uv) uv[0] = uv[1] = 1;
            }
            part.faces.push_back(f);
        }
        parts.push_back(std::move(part));
    }
}

