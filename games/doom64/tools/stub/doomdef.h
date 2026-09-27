/* stub for building the decomp's decodes.c natively (dirty-room tool) */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned char byte;
#define PU_STATIC 1
#define Z_Alloc(n, t, u) malloc(n)
#define Z_Free(p) free(p)
#define D_memset(p, v, n) memset(p, v, n)
#define I_Error(...) do { fprintf(stderr, __VA_ARGS__); exit(2); } while (0)
#include <limits.h>
#define MAXINT INT_MAX
typedef int boolean;
#define true 1
#define false 0
