// Dünne C-Schnittstelle: ruft das unveränderte main() des jype-Konverters in-process auf.
// Python (ctypes) ruft dw2_convert(quellordner, zielordner) auf; 0 = Erfolg.
#include <exception>
#include <string>
#include <vector>
#include <cstdio>
#ifdef DW2_ANDROID
#include <android/log.h>
#define DW2_LOG(...) __android_log_print(ANDROID_LOG_ERROR, "dw2conv", __VA_ARGS__)
#else
#define DW2_LOG(...) std::fprintf(stderr, __VA_ARGS__)
#endif

int dw2_upstream_main(int argc, char** argv);  // C++-Bindung: main wurde per Define umbenannt

extern "C" __attribute__((visibility("default"))) int dw2_convert(const char* source, const char* output) {
    if (!source || !output) return 2;
    std::string program = "dw2_model_converter", src = source, dst = output;
    std::vector<char*> argv = {program.data(), src.data(), dst.data(), nullptr};
    try {
        int code = dw2_upstream_main(3, argv.data());
        if (code) DW2_LOG("Konverter-Rückgabecode %d\n", code);
        return code;
    } catch (const std::exception& e) {
        DW2_LOG("Ausnahme: %s\n", e.what());
        return 3;
    } catch (...) {
        return 4;
    }
}
