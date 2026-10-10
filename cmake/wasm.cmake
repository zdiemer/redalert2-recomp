# Keep the game image at 0x00400000..0x00C04000 and place the WASM program
# above it. Guest addresses remain real 32-bit linear-memory pointers.
find_package(Python3 REQUIRED COMPONENTS Interpreter)
set(HLE "${CMAKE_BINARY_DIR}/hle")
execute_process(COMMAND "${Python3_EXECUTABLE}"
  "${CMAKE_SOURCE_DIR}/tools/wasm/prepare_runtime.py" "${PCRECOMP}" "${HLE}"
  COMMAND_ERROR_IS_FATAL ANY)
file(GLOB HLE_SOURCES CONFIGURE_DEPENDS "${HLE}/*.c")
list(FILTER HLE_SOURCES EXCLUDE REGEX "_selftest\\.c$")
add_executable(ra2 src/linux/main.c src/linux/blowfish.c src/linux/script.c
  src/linux/mods.c src/runtime/hdvox.c ${HLE_SOURCES} ${GEN_SOURCES})
target_include_directories(ra2 PRIVATE src/linux src/runtime ${GEN_DIR} ${HLE})
target_compile_definitions(ra2 PRIVATE RECOMP_RETADDR=0u RECOMP_FLAT_MEMORY RECOMP_LOCAL_REGS)
target_compile_options(ra2 PRIVATE -pthread -fno-strict-aliasing -fwrapv -sUSE_SDL=2 -sUSE_SDL_TTF=2)
set(GEN_OPT "-O2" CACHE STRING "optimisation for the generated C")
set_source_files_properties(${GEN_SOURCES} PROPERTIES COMPILE_OPTIONS "-w;${GEN_OPT}")
target_link_options(ra2 PRIVATE -pthread -sUSE_SDL=2 -sUSE_SDL_TTF=2
  -sGLOBAL_BASE=16777216 -sINITIAL_MEMORY=536870912 -sMAXIMUM_MEMORY=2147483648
  -sALLOW_MEMORY_GROWTH=1 -sSTACK_SIZE=16777216 -sDEFAULT_PTHREAD_STACK_SIZE=2097152
  -sPROXY_TO_PTHREAD=1 -sPTHREAD_POOL_SIZE=8 -sOFFSCREENCANVAS_SUPPORT=1
  -sOFFSCREEN_FRAMEBUFFER=1 -sEXIT_RUNTIME=1 -sFORCE_FILESYSTEM=1
  "-sEXPORTED_RUNTIME_METHODS=['FS','callMain']" -sINVOKE_RUN=0
  "--shell-file=${CMAKE_SOURCE_DIR}/web/shell.html")
set_target_properties(ra2 PROPERTIES SUFFIX ".html")
