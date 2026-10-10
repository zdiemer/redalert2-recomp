# Keep the game image at 0x00400000..0x00C04000 and place the WASM program
# above it. Guest addresses remain real 32-bit linear-memory pointers.
find_package(Python3 REQUIRED COMPONENTS Interpreter)
set(HLE "${CMAKE_BINARY_DIR}/hle")
execute_process(COMMAND "${Python3_EXECUTABLE}"
  "${CMAKE_SOURCE_DIR}/tools/wasm/prepare_runtime.py" "${PCRECOMP}" "${HLE}"
  COMMAND_ERROR_IS_FATAL ANY)
file(GLOB HLE_SOURCES CONFIGURE_DEPENDS "${HLE}/*.c")
list(FILTER HLE_SOURCES EXCLUDE REGEX "_selftest\\.c$")
list(FILTER HLE_SOURCES EXCLUDE REGEX "/screen\\.c$")
add_executable(ra2 src/linux/main.c src/linux/blowfish.c src/linux/script.c
  src/linux/mods.c src/runtime/hdvox.c src/wasm/screen.c ${HLE_SOURCES} ${GEN_SOURCES})
target_include_directories(ra2 PRIVATE src/linux src/runtime ${GEN_DIR} ${HLE})
set(FFMPEG_WASM "${CMAKE_SOURCE_DIR}/.deps/ffmpeg-wasm/install")
if(NOT EXISTS "${FFMPEG_WASM}/lib/libavformat.a")
  message(FATAL_ERROR "Build the Bink decoder first: python tools/wasm/build_ffmpeg.py")
endif()
set_source_files_properties("${HLE}/bink.c" PROPERTIES
  INCLUDE_DIRECTORIES "${FFMPEG_WASM}/include" COMPILE_DEFINITIONS HLE_WITH_FFMPEG)
target_link_libraries(ra2 PRIVATE
  "${FFMPEG_WASM}/lib/libavformat.a" "${FFMPEG_WASM}/lib/libavcodec.a"
  "${FFMPEG_WASM}/lib/libswresample.a" "${FFMPEG_WASM}/lib/libavutil.a")
target_compile_definitions(ra2 PRIVATE RECOMP_RETADDR=0u RECOMP_FLAT_MEMORY RECOMP_LOCAL_REGS)
target_compile_options(ra2 PRIVATE -pthread -fno-strict-aliasing -fwrapv -sUSE_SDL=2 -sUSE_SDL_TTF=2)
# LLVM's -O2 simplifies large lifted functions before V8 sees them. The -O1
# build exhausted Chrome's native compiler memory during Allied playback.
set(GEN_OPT "-O2" CACHE STRING "optimisation for the generated C")
set_source_files_properties(${GEN_SOURCES} PROPERTIES COMPILE_OPTIONS "-w;${GEN_OPT}")
target_link_options(ra2 PRIVATE -O1 -g2 -pthread -sUSE_SDL=2 -sUSE_SDL_TTF=2
  -sGLOBAL_BASE=16777216 -sINITIAL_MEMORY=536870912 -sMAXIMUM_MEMORY=2147483648
  -sALLOW_MEMORY_GROWTH=1 -sSTACK_SIZE=16777216 -sDEFAULT_PTHREAD_STACK_SIZE=2097152
  -sPROXY_TO_PTHREAD=1 -sPTHREAD_POOL_SIZE=8
  -sOFFSCREEN_FRAMEBUFFER=1 -sEXIT_RUNTIME=1 -sFORCE_FILESYSTEM=1
  "-sEXPORTED_RUNTIME_METHODS=['FS','callMain']" -sINVOKE_RUN=0
  "--shell-file=${CMAKE_SOURCE_DIR}/web/shell.html")
set_target_properties(ra2 PROPERTIES SUFFIX ".html")
set_property(TARGET ra2 APPEND PROPERTY LINK_DEPENDS "${CMAKE_SOURCE_DIR}/web/shell.html")
