cmake_minimum_required(VERSION 3.15)
project(test_package LANGUAGES C)

find_package(secp256k1 REQUIRED CONFIG)

add_executable(${PROJECT_NAME} test_package.c)
target_link_libraries(${PROJECT_NAME} PRIVATE secp256k1::secp256k1)
