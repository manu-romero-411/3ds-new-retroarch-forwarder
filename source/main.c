#include <3ds.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SD_PREFIX        "sdmc:/"
#define MAX_PATH_LEN     512

#define HOMEBREW_LAUNCHER_TITLE_ID  0x000400000D921E00ULL
#define HOMEBREW_LAUNCHER_MEDIATYPE MEDIATYPE_SD

static void fatal_error(const char *fmt, ...)
{
    gfxInitDefault();
    consoleInit(GFX_TOP, NULL);

    va_list args;
    va_start(args, fmt);
    vprintf(fmt, args);
    va_end(args);

    printf("\n\nPress START to exit.\n");

    while (aptMainLoop())
    {
        hidScanInput();
        u32 kDown = hidKeysDown();
        if (kDown & KEY_START)
            break;

        gfxFlushBuffers();
        gfxSwapBuffers();
        gspWaitForVBlank();
    }

    gfxExit();
    exit(1);
}

static void read_sd_path_from_romfs(const char *romfs_path, char *out, size_t out_size)
{
    FILE *f = fopen(romfs_path, "rb");
    if (!f)
        fatal_error("ERROR: Cannot open %s", romfs_path);

    char buf[MAX_PATH_LEN];
    size_t n = fread(buf, 1, sizeof(buf) - 1, f);
    fclose(f);

    if (n == 0)
        fatal_error("ERROR: File empty: %s", romfs_path);

    buf[n] = '\0';

    while (n > 0 && (buf[n-1] == '\n' || buf[n-1] == '\r' || buf[n-1] == ' '))
        buf[--n] = '\0';

    if (n == 0)
        fatal_error("ERROR: Path is empty");

    if (snprintf(out, out_size, "%s%s", SD_PREFIX, buf) >= (int)out_size)
        fatal_error("ERROR: Path too long");
}

static Result hbldr_set_target(Handle hbldr, const char *path)
{
    if (strncmp(path, "sdmc:/", 6) == 0)
        path += 5;

    u32 pathSize = strlen(path) + 1;
    u32 *cmdbuf = getThreadCommandBuffer();

    cmdbuf[0] = IPC_MakeHeader(0x2, 0, 2);
    cmdbuf[1] = IPC_Desc_StaticBuffer(pathSize, 0);
    cmdbuf[2] = (u32)path;

    Result rc = svcSendSyncRequest(hbldr);
    if (R_FAILED(rc))
        return rc;

    return (Result)cmdbuf[1];
}

static Result hbldr_set_argv(Handle hbldr, u8 *argvBuf, u32 argvSize)
{
    u32 *cmdbuf = getThreadCommandBuffer();
    cmdbuf[0] = IPC_MakeHeader(0x3, 0, 2);
    cmdbuf[1] = IPC_Desc_StaticBuffer(argvSize, 1);
    cmdbuf[2] = (u32)argvBuf;

    Result rc = svcSendSyncRequest(hbldr);
    if (R_FAILED(rc))
        return rc;

    return (Result)cmdbuf[1];
}

int main(void)
{
    gfxInitDefault();
    consoleInit(GFX_TOP, NULL);
    
    printf("Loading paths...\n");

    Result rc = romfsInit();
    if (R_FAILED(rc))
    {
        fatal_error("romfsInit failed");
    }

    char core_path[MAX_PATH_LEN];
    char content_path[MAX_PATH_LEN];

    read_sd_path_from_romfs("romfs:/core.path", core_path, sizeof(core_path));
    read_sd_path_from_romfs("romfs:/content.path", content_path, sizeof(content_path));

    romfsExit();

    printf("Core: %s\n", core_path);
    printf("Content: %s\n\n", content_path);

    printf("Connecting to hb:ldr...\n");
    
    Handle hbldr;
    rc = svcConnectToPort(&hbldr, "hb:ldr");
    if (R_FAILED(rc))
    {
        fatal_error("svcConnectToPort failed: 0x%08lX", rc);
    }

    printf("Setting target...\n");
    rc = hbldr_set_target(hbldr, core_path);
    if (R_FAILED(rc))
    {
        fatal_error("hbldr_set_target failed: 0x%08lX", rc);
    }

    printf("Setting argv...\n");
    
    // Allocate in linear memory
    u8 *argvBuf = linearAlloc(0x400);
    if (!argvBuf)
    {
        fatal_error("linearAlloc failed");
    }

    memset(argvBuf, 0, 0x400);
    
    // Build argv buffer.
    // IMPORTANTE: a diferencia de SetTarget (que sí necesita la ruta sin el
    // prefijo "sdmc:/" para que hb:ldr localice el fichero), el argv que
    // recibe el proceso lanzado debe conservar "sdmc:/" intacto, igual que
    // hace RetroArch en exec_3dsx.c (el path se strippea solo en la
    // variable local que usa launchFile() para SetTarget, nunca en el
    // buffer de argv). Si se quita aquí, RetroArch resuelve mal rutas
    // relativas a partir de argv[0]/argv[1] y crashea igual con cualquier
    // core.
    // El contador argc ocupa un u32 COMPLETO (4 bytes), no 1 byte: si las
    // cadenas empiezan antes de offset 4 se pisan los bytes altos de argc
    // y __system_initArgv() (libctru) se lía recorriendo memoria con un
    // argc corrupto -> esa es la causa real del crash, no el prefijo sdmc:/.
    size_t off = sizeof(u32);
    const char *cpath = core_path;
    const char *spath = content_path;

    size_t clen = strlen(cpath) + 1;
    size_t slen = strlen(spath) + 1;
    
    argvBuf[0] = 2;
    memcpy(&argvBuf[off], cpath, clen);
    off += clen;
    memcpy(&argvBuf[off], spath, slen);
    off += slen;

    rc = hbldr_set_argv(hbldr, argvBuf, off);
    if (R_FAILED(rc))
    {
        fatal_error("hbldr_set_argv failed: 0x%08lX", rc);
    }

    linearFree(argvBuf);
    svcCloseHandle(hbldr);

    printf("Chainloading...\n");
    aptSetChainloader(HOMEBREW_LAUNCHER_TITLE_ID, HOMEBREW_LAUNCHER_MEDIATYPE);

    gfxExit();
    return 0;
}