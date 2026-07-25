# bootstrap/backend/runtime.py
"""
Embedded C runtime for Nala intrinsics and basic types.
"""

RUNTIME_C = r"""
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>

/* NalaSlice: view into byte array */
typedef struct { uint8_t* data; size_t len; } NalaSlice;

/* Slice intrinsics */
size_t __intrinsic_byte_len(NalaSlice s) { return s.len; }
NalaSlice __intrinsic_as_bytes(NalaSlice s) { return s; }
NalaSlice __intrinsic_slice_bytes(NalaSlice s, size_t start, size_t end) {
    if (start > s.len) start = s.len;
    if (end > s.len) end = s.len;
    if (start >= end) return (NalaSlice){NULL, 0};
    size_t out_len = end - start;
    uint8_t* data = (uint8_t*)malloc(out_len);
    if (data) { memcpy(data, s.data + start, out_len); return (NalaSlice){data, out_len}; }
    return (NalaSlice){NULL, 0};
}
uint8_t __intrinsic_byte_at(NalaSlice s, size_t index) {
    if (index >= s.len) return 0;
    return s.data[index];
}

/* Print intrinsics */
void __intrinsic_print_usize(size_t x)   { printf("%zu\n", x); }
void __intrinsic_print_u8(uint8_t x)     { printf("%u\n", x); }
void __intrinsic_print_u16(uint16_t x)   { printf("%u\n", x); }
void __intrinsic_print_u32(uint32_t x)   { printf("%u\n", x); }
void __intrinsic_print_u64(uint64_t x)   { printf("%llu\n", (unsigned long long)x); }
void __intrinsic_print_i8(int8_t x)      { printf("%d\n", x); }
void __intrinsic_print_i16(int16_t x)    { printf("%d\n", x); }
void __intrinsic_print_i32(int32_t x)    { printf("%d\n", x); }
void __intrinsic_print_i64(int64_t x)    { printf("%lld\n", (long long)x); }
void __intrinsic_print_f32(float x)      { printf("%f\n", x); }
void __intrinsic_print_f64(double x)     { printf("%f\n", x); }
void __intrinsic_print_bool(bool x)      { printf(x ? "true\n" : "false\n"); }
void __intrinsic_print_string(NalaSlice x) { printf("%s\n", (char*)x.data); }

/* Assert */
void __intrinsic_assert(bool cond) {
    if (!cond) { fprintf(stderr, "Assertion failed\n"); abort(); }
}
"""
