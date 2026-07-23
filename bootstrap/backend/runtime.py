"""
bootstrap/backend/runtime.py

Runtime C code embedded as Python strings.

FUNGSI:
    Runtime menyediakan implementasi C untuk fungsi-fungsi bawaan (intrinsic)
    dan tipe data dasar yang digunakan oleh kode hasil kompilasi Nala.

ARSITEKTUR:
    Runtime di-inject ke dalam output C code oleh codegen.py.
    Dulu runtime ada di file terpisah bootstrap_runtime.c, tapi sekarang
    langsung di-inject dari sini supaya bootstrap compiler self-contained
    (tidak depend file eksternal).

KOMPONEN RUNTIME:
    1. Tipe Data Dasar:
       - NalaSlice: Representasi slice []u8 (string/bytes)
    
    2. Intrinsics untuk String/Slice:
       - byte_len: Mendapatkan panjang slice
       - as_bytes: Konversi ke bytes (identity untuk []u8)
       - slice_bytes: Membuat slice baru dari range
       - byte_at: Mengambil byte pada index tertentu
    
    3. Intrinsics untuk Print:
       - print_u8, print_u16, print_u32, print_u64
       - print_i8, print_i16, print_i32, print_i64
       - print_f32, print_f64
       - print_bool
       - print_string

PRINSIP DESAIN:
    - Runtime ditulis dalam C murni (portable)
    - Fungsi intrinsik memiliki prefix __intrinsic_ untuk menghindari collision
    - Memory management sederhana (malloc tanpa free di stage0)
    - Tipe data minimalis (hanya slice untuk string/bytes)
"""

RUNTIME_C = r"""
/* === Nala Bootstrap Runtime (embedded) === */

#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>

/* --- NalaSlice: representasi slice []u8 --- */
/**
 * NalaSlice - Representasi slice/string di Nala.
 * 
 * Slice adalah view ke array of bytes:
 *     - data: Pointer ke byte array (uint8_t*)
 *     - len: Panjang slice (size_t)
 * 
 * Digunakan untuk:
 *     - String literals ("hello")
 *     - Byte arrays ([]u8)
 *     - Substrings (slice operations)
 * 
 * Catatan: Slice TIDAK memiliki ownership - hanya view.
 * Memory management dilakukan oleh caller.
 */
typedef struct {
    uint8_t* data;
    size_t len;
} NalaSlice;

/* --- String/slice intrinsics --- */

/**
 * byte_len - Mendapatkan panjang slice.
 * 
 * Args:
 *     s: NalaSlice yang akan diukur
 * 
 * Returns:
 *     size_t: Panjang slice dalam bytes
 * 
 * Contoh:
 *     let len = byte_len!("hello");  // len = 5
 */
size_t __intrinsic_byte_len(NalaSlice s) {
    return s.len;
}

/**
 * as_bytes - Konversi ke bytes (identity untuk []u8).
 * 
 * Untuk tipe []u8, ini adalah identity function.
 * Berguna untuk konsistensi API.
 * 
 * Args:
 *     s: NalaSlice yang akan dikonversi
 * 
 * Returns:
 *     NalaSlice: Slice yang sama (identity)
 */
NalaSlice __intrinsic_as_bytes(NalaSlice s) {
    // Identity function — []u8 is already bytes
    return s;
}

/**
 * slice_bytes - Membuat slice baru dari range [start, end).
 * 
 * Mengalokasikan memory baru dan menyalin byte dari range yang diminta.
 * 
 * Args:
 *     s: NalaSlice sumber
 *     start: Index awal (inclusive)
 *     end: Index akhir (exclusive)
 * 
 * Returns:
 *     NalaSlice: Slice baru dengan data yang disalin
 * 
 * Note:
 *     - Alokasi memory via malloc
 *     - Tidak ada automatic free di stage0
 *     - Bisa menyebabkan memory leak jika tidak dikelola
 *     - Bounds checking: start/end di-clamp ke range yang valid
 * 
 * Contoh:
 *     let s = "hello";
 *     let sub = slice_bytes!(s, 1, 4);  // "ell"
 */
NalaSlice __intrinsic_slice_bytes(NalaSlice s, size_t start, size_t end) {
    NalaSlice slice;
    if (start > s.len) start = s.len;
    if (end > s.len) end = s.len;
    if (start >= end) {
        slice.data = NULL;
        slice.len = 0;
        return slice;
    }
    size_t out_len = end - start;
    slice.data = (uint8_t*)malloc(out_len);
    if (slice.data) {
        memcpy(slice.data, s.data + start, out_len);
        slice.len = out_len;
    } else {
        slice.len = 0;
    }
    return slice;
}

/**
 * byte_at - Mengambil byte pada index tertentu.
 * 
 * Args:
 *     s: NalaSlice sumber
 *     index: Index byte yang diambil (0-indexed)
 * 
 * Returns:
 *     uint8_t: Nilai byte pada index, atau 0 jika index out of bounds
 * 
 * Contoh:
 *     let b = byte_at!("hello", 1);  // b = 'e'
 */
uint8_t __intrinsic_byte_at(NalaSlice s, size_t index) {
    if (index >= s.len) return 0;
    return s.data[index];
}

/* --- Print intrinsics --- */

/**
 * Fungsi-fungsi print untuk berbagai tipe data.
 * 
 * Setiap tipe memiliki fungsi print sendiri:
 *     - Integer: unsigned (u8, u16, u32, u64) dan signed (i8, i16, i32, i64)
 *     - Float: f32, f64
 *     - Boolean: print_bool
 *     - String: print_string (menerima NalaSlice)
 * 
 * Semua fungsi print menambahkan newline ('\n') di akhir.
 * 
 * Contoh:
 *     print_u8!(42);        // "42\n"
 *     print_bool!(true);    // "true\n"
 *     print_string!("hello"); // "hello\n"
 */

/* Unsigned integers */
void __intrinsic_print_u8(uint8_t x)   { printf("%u\n", x); }
void __intrinsic_print_u16(uint16_t x) { printf("%u\n", x); }
void __intrinsic_print_u32(uint32_t x) { printf("%u\n", x); }
void __intrinsic_print_u64(uint64_t x) { printf("%llu\n", (unsigned long long)x); }

/* Signed integers */
void __intrinsic_print_i8(int8_t x)    { printf("%d\n", x); }
void __intrinsic_print_i16(int16_t x)  { printf("%d\n", x); }
void __intrinsic_print_i32(int32_t x)  { printf("%d\n", x); }
void __intrinsic_print_i64(int64_t x)  { printf("%lld\n", (long long)x); }

/* Floating point */
void __intrinsic_print_f32(float x)    { printf("%f\n", x); }
void __intrinsic_print_f64(double x)   { printf("%f\n", x); }

/* Boolean */
void __intrinsic_print_bool(bool x)    { printf(x ? "true\n" : "false\n"); }

/* String (NalaSlice) */
void __intrinsic_print_string(NalaSlice x) { printf("%s\n", (char*)x.data); }

/* Assert intrinsic */
/* assert - Abort program jika condition false. */
void __intrinsic_assert(bool cond) {
    if (!cond) {
        fprintf(stderr, "Assertion failed\n");
        abort();
    }
}
"""
