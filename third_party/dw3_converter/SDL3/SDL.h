// Minimal headless export adapter. No SDL runtime is linked.
#pragma once
#include <cstdint>
struct SDL_Surface { int w, h, pitch; void *pixels; };
constexpr int SDL_PIXELFORMAT_RGBA32 = 0;
bool SDL_CreateDirectory(const char *path);
SDL_Surface *SDL_CreateSurfaceFrom(int w, int h, int, void *pixels, int pitch);
bool SDL_SavePNG(SDL_Surface *surface, const char *path);
void SDL_DestroySurface(SDL_Surface *surface);
