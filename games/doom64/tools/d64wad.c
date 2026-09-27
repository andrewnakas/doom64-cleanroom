/* Dirty-room tool: split DOOM64.WAD into decompressed lumps.
 *
 *   d64wad <DOOM64.WAD> <outdir>
 *
 * Writes <outdir>/NNNN.lmp for every lump plus <outdir>/index.tsv
 * (index, name, compressed, method, size, stored size). Uses the decomp's own
 * decoders (decodes.c, built against stub headers).
 * Method: textures (T_START..T_END), maps (MAPxx) and demos use DecodeD64;
 * everything else DecodeJaguar, as in the game's W_CacheLump* calls.
 */
#include "gen/decodes.c"

typedef struct { int filepos, size; char name[8]; } lump_t;

static unsigned char *slurp(const char *path, long *len) {
    FILE *f = fopen(path, "rb");
    if (!f) { perror(path); exit(1); }
    fseek(f, 0, SEEK_END); *len = ftell(f); fseek(f, 0, SEEK_SET);
    unsigned char *b = malloc(*len);
    fread(b, 1, *len, f); fclose(f);
    return b;
}

int main(int argc, char **argv) {
    long len;
    char path[1024];
    if (argc < 3) { fprintf(stderr, "usage: d64wad wad outdir\n"); return 1; }
    unsigned char *wad = slurp(argv[1], &len);
    int num = *(int *)(wad + 4), ofs = *(int *)(wad + 8);
    lump_t *dir = (lump_t *)(wad + ofs);
    snprintf(path, sizeof path, "%s/index.tsv", argv[2]);
    FILE *idx = fopen(path, "w");
    int intex = 0, ncomp = 0;
    unsigned char *out = malloc(8 << 20);
    for (int i = 0; i < num; i++) {
        char name[9] = {0};
        memcpy(name, dir[i].name, 8);
        int comp = name[0] & 0x80;
        name[0] &= 0x7f;
        if (!strcmp(name, "T_START")) intex = 1;
        if (!strcmp(name, "T_END")) intex = 0;
        int d64 = intex || !strncmp(name, "MAP", 3) || !strncmp(name, "DEMO", 4);
        int stored = (i + 1 < num ? dir[i + 1].filepos : ofs) - dir[i].filepos;
        if (!comp) stored = dir[i].size;
        memset(out, 0, dir[i].size + 16);
        if (comp) {
            if (d64) DecodeD64(wad + dir[i].filepos, out);
            else DecodeJaguar(wad + dir[i].filepos, out);
            ncomp++;
        } else if (dir[i].size) {
            memcpy(out, wad + dir[i].filepos, dir[i].size);
        }
        snprintf(path, sizeof path, "%s/%04d.lmp", argv[2], i);
        FILE *f = fopen(path, "wb");
        fwrite(out, 1, dir[i].size, f); fclose(f);
        fprintf(idx, "%d\t%s\t%d\t%s\t%d\t%d\n", i, name, comp ? 1 : 0,
                comp ? (d64 ? "d64" : "jag") : "raw", dir[i].size, stored);
    }
    fclose(idx);
    printf("lumps %d compressed %d\n", num, ncomp);
    return 0;
}
