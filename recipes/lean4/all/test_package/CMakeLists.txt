cmake_minimum_required(VERSION 3.15)
project(test_package LANGUAGES C)

find_package(lean4 REQUIRED CONFIG)

# The default target (runtime plus Lake) and the runtime-only component.
add_executable(test_package test_package.c)
target_link_libraries(test_package PRIVATE lean4::lean4)

add_executable(test_leanshared test_package.c)
target_link_libraries(test_leanshared PRIVATE lean4::leanshared)
