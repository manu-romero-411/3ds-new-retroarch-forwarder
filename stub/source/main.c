#include <3ds.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#include "cores_table.h"

#define SD_PREFIX        "sdmc:/"
#define MAX_PATH_LEN     512
#define FILE_CHUNK_SIZE  4096
#define CORE_NAME_MAXLEN 64
#define CORES_SD_DIR     "retroarch/cores/"

/* Set to true once the console has been initialized, so a later
 * fatal_error() does not clear a message that is already on screen. */
static bool g_console_ready = false;

/* Last install error, filled by installCia() and shown by the caller. */
static char g_install_err[MAX_PATH_LEN + 64];

/* SHA-256("ARGV") - used by libctru's __system_initArgv() */
static char argvHmac[0x20] = {
    0x1d, 0x78, 0xff, 0xb9, 0xc5, 0xbc, 0x78, 0xb7,
    0xac, 0x29, 0x1d, 0x3e, 0x16, 0xd0, 0xcf, 0x53,
    0xef, 0x12, 0x58, 0x83, 0xb6, 0x9e, 0x2f, 0x79,
    0x47, 0xf9, 0x35, 0x61, 0xeb, 0x50, 0xd7, 0x67
};

typedef struct {
    u32 argc;
    char args[0x300 - 0x4];
} ciaParam;

/* Shows an error on the top screen and waits for START. The console is
 * created lazily here, so nothing is drawn during a normal launch. */
static void fatal_error(const char *fmt, ...)
{
    if (!g_console_ready)
    {
        if (!gspHasGpuRight())
            gfxInitDefault();
        consoleInit(GFX_TOP, NULL);
        g_console_ready = true;
    }

    va_list args;
    va_start(args, fmt);
    vprintf(fmt, args);
    va_end(args);

    printf("\n\nPress START to exit.\n");

    while (aptMainLoop())
    {
        hidScanInput();
        if (hidKeysDown() & KEY_START)
            break;

        gfxFlushBuffers();
        gfxSwapBuffers();
        gspWaitForVBlank();
    }

    gfxExit();
    exit(1);
}

/* Reads a single-line text file from RomFS into buf, trimming trailing
 * whitespace/newlines. Aborts with an error if it is missing or empty. */
static void read_line_from_romfs(const char *romfs_path, char *buf, size_t buf_size)
{
    FILE *f = fopen(romfs_path, "rb");
    if (!f)
        fatal_error("Missing RomFS file:\n%s", romfs_path);

    size_t n = fread(buf, 1, buf_size - 1, f);
    fclose(f);

    while (n > 0 && (buf[n - 1] == '\n' || buf[n - 1] == '\r' || buf[n - 1] == ' '))
        n--;
    buf[n] = '\0';

    if (n == 0)
        fatal_error("Empty RomFS file:\n%s", romfs_path);
}

static void read_sd_path_from_romfs(const char *romfs_path, char *out, size_t out_size)
{
    char buf[MAX_PATH_LEN];
    read_line_from_romfs(romfs_path, buf, sizeof(buf));

    if (snprintf(out, out_size, "%s%s", SD_PREFIX, buf) >= (int)out_size)
        fatal_error("Path too long in:\n%s", romfs_path);
}

static void read_core_name_from_romfs(const char *romfs_path, char *out, size_t out_size)
{
    char buf[CORE_NAME_MAXLEN];
    read_line_from_romfs(romfs_path, buf, sizeof(buf));

    if (snprintf(out, out_size, "%s", buf) >= (int)out_size)
        fatal_error("Core name too long in:\n%s", romfs_path);
}

static const core_entry_t *lookup_core(const char *libretro_name)
{
    for (size_t i = 0; i < CORES_TABLE_COUNT; i++)
    {
        if (strcmp(CORES_TABLE[i].libretro_name, libretro_name) == 0)
            return &CORES_TABLE[i];
    }
    return NULL;
}

static bool file_exists(const char *path)
{
    struct stat st;
    return stat(path, &st) == 0;
}

/* Returns 1 if the title exists on the SD card (any version), 0 if not,
 * -1 on error. */
static int isCoreInstalled(u64 titleId)
{
    u32 titlesToRetrieve;
    u32 titlesRetrieved;
    int found = 0;

    if (R_FAILED(AM_GetTitleCount(MEDIATYPE_SD, &titlesToRetrieve)))
        return -1;

    u64 *titleIds = malloc(titlesToRetrieve * sizeof(u64));
    if (!titleIds)
        return -1;

    if (R_FAILED(AM_GetTitleList(&titlesRetrieved, MEDIATYPE_SD, titlesToRetrieve, titleIds)))
    {
        free(titleIds);
        return -1;
    }

    for (u32 i = 0; i < titlesRetrieved; i++)
    {
        if (titleIds[i] == titleId)
        {
            found = 1;
            break;
        }
    }

    free(titleIds);
    return found;
}

/* Installs a CIA from the SD card. Returns 1 on success (or if it already
 * exists), -1 on failure with the reason stored in g_install_err. */
static int installCia(const char *ciaPath)
{
    Handle ciaFile;
    FS_Archive ciaArchive;
    Handle outputHandle;
    u64 fileSize;
    u32 bytesRead;
    u32 bytesWritten;
    u8 transferBuffer[FILE_CHUNK_SIZE];
    u64 fileOffset = 0;
    Result res;

    res = FSUSER_OpenArchive(&ciaArchive, ARCHIVE_SDMC, fsMakePath(PATH_EMPTY, ""));
    if (R_FAILED(res))
    {
        snprintf(g_install_err, sizeof(g_install_err),
                 "Cannot open SD archive (0x%08lX)", res);
        return -1;
    }

    /* Skip only "sdmc:" (5 chars), NOT "sdmc:/": FSUSER needs the leading
     * slash ("/retroarch/cores/xxx.cia"), like RetroArch's exec_cia.c. */
    const char *relPath = ciaPath;
    if (strncmp(relPath, "sdmc:", 5) == 0)
        relPath += 5;

    res = FSUSER_OpenFile(&ciaFile, ciaArchive, fsMakePath(PATH_ASCII, relPath), FS_OPEN_READ, 0);
    if (R_FAILED(res))
    {
        snprintf(g_install_err, sizeof(g_install_err),
                 "Cannot open CIA (0x%08lX):\n%s", res, ciaPath);
        FSUSER_CloseArchive(ciaArchive);
        return -1;
    }

    res = AM_StartCiaInstall(MEDIATYPE_SD, &outputHandle);
    if (R_FAILED(res))
    {
        snprintf(g_install_err, sizeof(g_install_err),
                 "Cannot start CIA install (0x%08lX)", res);
        goto fail_close;
    }

    res = FSFILE_GetSize(ciaFile, &fileSize);
    if (R_FAILED(res))
    {
        snprintf(g_install_err, sizeof(g_install_err),
                 "Cannot get CIA size (0x%08lX)", res);
        goto fail_cancel;
    }

    while (fileOffset < fileSize)
    {
        u64 bytesRemaining = fileSize - fileOffset;
        u32 chunkSize = bytesRemaining < FILE_CHUNK_SIZE ? (u32)bytesRemaining : FILE_CHUNK_SIZE;

        res = FSFILE_Read(ciaFile, &bytesRead, fileOffset, transferBuffer, chunkSize);
        if (R_FAILED(res))
        {
            snprintf(g_install_err, sizeof(g_install_err),
                     "CIA read failed (0x%08lX)", res);
            goto fail_cancel;
        }

        res = FSFILE_Write(outputHandle, &bytesWritten, fileOffset,
                           transferBuffer, bytesRead, FS_WRITE_FLUSH);
        if (R_FAILED(res))
        {
            AM_CancelCIAInstall(outputHandle);
            FSFILE_Close(ciaFile);
            FSUSER_CloseArchive(ciaArchive);
            if (R_DESCRIPTION(res) == RD_ALREADY_EXISTS)
                return 1; /* Already exists, that's ok */
                snprintf(g_install_err, sizeof(g_install_err),
                         "CIA write failed (0x%08lX)", res);
                return -1;
        }

        if (bytesWritten != bytesRead)
        {
            snprintf(g_install_err, sizeof(g_install_err), "CIA write size mismatch");
            goto fail_cancel;
        }

        fileOffset += bytesWritten;
    }

    res = AM_FinishCiaInstall(outputHandle);
    if (R_FAILED(res))
    {
        snprintf(g_install_err, sizeof(g_install_err),
                 "Cannot finish CIA install (0x%08lX)", res);
        goto fail_close;
    }

    FSFILE_Close(ciaFile);
    FSUSER_CloseArchive(ciaArchive);
    return 1;

    fail_cancel:
    AM_CancelCIAInstall(outputHandle);
    fail_close:
    FSFILE_Close(ciaFile);
    FSUSER_CloseArchive(ciaArchive);
    return -1;
}

int main(void)
{
    Result rc = romfsInit();
    if (R_FAILED(rc))
        fatal_error("romfsInit failed (0x%08lX)", rc);

    char core_name[CORE_NAME_MAXLEN];
    char content_path[MAX_PATH_LEN];
    char core_cia_path[MAX_PATH_LEN];

    /* Config from RomFS: only the core name (libretro_name) and the content
     * path. Title ID and CIA filename come from CORES_TABLE. */
    read_core_name_from_romfs("romfs:/core.txt", core_name, sizeof(core_name));
    read_sd_path_from_romfs("romfs:/content.path", content_path, sizeof(content_path));

    romfsExit();

    const core_entry_t *core = lookup_core(core_name);
    if (!core)
        fatal_error("Unknown core '%s'\n(is cores_table.h out of date?)", core_name);

    u64 core_title_id = core->title_id;
    if (snprintf(core_cia_path, sizeof(core_cia_path), "%s%s%s",
        SD_PREFIX, CORES_SD_DIR, core->cia_filename) >= (int)sizeof(core_cia_path))
        fatal_error("CIA path too long for core '%s'", core_name);

    /* The ROM must exist before doing anything else. */
    if (!file_exists(content_path))
        fatal_error("ROM not found:\n%s", content_path);

    if (R_FAILED(amInit()) || R_FAILED(fsInit()))
        fatal_error("Cannot initialize AM/FS services");

    int coreInstalled = isCoreInstalled(core_title_id);
    if (coreInstalled == -1)
        fatal_error("Could not read the installed title list");

    /* Already installed is not an error: skip silently. The CIA is only
     * required (and only checked) when the core is missing. */
    if (coreInstalled == 0)
    {
        if (!file_exists(core_cia_path))
            fatal_error("Core CIA not found:\n%s", core_cia_path);

        if (installCia(core_cia_path) == -1)
            fatal_error("Core install failed:\n%s", g_install_err);
    }

    /* Build the argument buffer for RetroArch. */
    ciaParam param;
    param.argc = 0;
    int argsLength = 0;
    char *argLocation = param.args;

    /* argv[0]: dummy program name. It must be present: the content goes in
     * argv[1], as in RetroArch's exec_cia.c. Without it, RetroArch starts
     * without detecting any ROM. */
    static const char *arg0 = "retroarch";
    strcpy(argLocation, arg0);
    argLocation += strlen(arg0) + 1;
    argsLength += strlen(arg0) + 1;
    param.argc++;

    /* argv[1]: path to the content to load */
    strcpy(argLocation, content_path);
    argLocation += strlen(content_path) + 1;
    argsLength += strlen(content_path) + 1;
    param.argc++;

    Result res = APT_PrepareToDoApplicationJump(0, core_title_id, 0x1);
    if (R_FAILED(res))
        fatal_error("Cannot prepare jump to core (0x%08lX)", res);

    res = APT_DoApplicationJump(&param, sizeof(param.argc) + argsLength, argvHmac);
    if (R_FAILED(res))
        fatal_error("Cannot jump to core (0x%08lX)", res);

    /* Should never reach here. */
    amExit();
    fsExit();
    return 0;
}
