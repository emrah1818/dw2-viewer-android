cmake_minimum_required(VERSION 3.22.1)
project(dw2conv LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Befüllt von tools/fetch_deps.sh: Konverter von jype (MIT) samt Submodulen + Fallback-Header.
set(DEPS ${CMAKE_CURRENT_LIST_DIR}/deps)
set(UP ${DEPS}/dw2_model_converter)
file(GLOB UPSTREAM_SRC ${UP}/src/*.cpp ${UP}/src/*.cc)
if(NOT UPSTREAM_SRC)
  message(FATAL_ERROR "Upstream-Konverter fehlt. Zuerst tools/fetch_deps.sh ausführen.")
endif()

# Alle Header-Ordner einsammeln (src, Submodule wie glm/json/tinygltf/stb, Fallbacks).
file(GLOB_RECURSE HEADERS ${DEPS}/*.h ${DEPS}/*.hpp ${DEPS}/*.inl)
set(INCLUDES ${UP}/src ${UP})
foreach(h ${HEADERS})
  get_filename_component(d ${h} DIRECTORY)
  list(APPEND INCLUDES ${d})
  get_filename_component(p ${d} DIRECTORY)
  list(APPEND INCLUDES ${p})
endforeach()
list(REMOVE_DUPLICATES INCLUDES)

add_library(dw2conv SHARED ${CMAKE_CURRENT_LIST_DIR}/dw2_entry.cpp ${UPSTREAM_SRC})
target_include_directories(dw2conv PRIVATE ${INCLUDES})
# Das originale main() des Konverters wird als dw2_upstream_main aufrufbar.
set_source_files_properties(${UPSTREAM_SRC} PROPERTIES COMPILE_DEFINITIONS "main=dw2_upstream_main")
target_compile_options(dw2conv PRIVATE -O2 -w)
if(ANDROID)
  target_link_options(dw2conv PRIVATE -Wl,-z,max-page-size=16384)   # 16-KB-Seiten (Play-Pflicht)
  target_link_libraries(dw2conv log)
  target_compile_definitions(dw2conv PRIVATE DW2_ANDROID=1)
endif()
