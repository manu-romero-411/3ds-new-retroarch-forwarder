#include <3ds.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <math.h>
#include <sys/stat.h>

#include "cores_table.h"

#define SD_PREFIX        "sdmc:/"
#define MAX_PATH_LEN     512
#define FILE_CHUNK_SIZE  4096
#define CORE_NAME_MAXLEN 64
#define CORES_SD_DIR     "retroarch/cores/"

/* Prevents fatal_error() from clearing the screen (via consoleInit) if the
 * console was already initialized and has useful earlier error messages on
 * screen (e.g. the real reason a CIA install failed). */
static bool g_console_ready = false;

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

    /* Trim whitespace and newlines */
    while (n > 0 && (buf[n-1] == '\n' || buf[n-1] == '\r' || buf[n-1] == ' '))
        buf[--n] = '\0';

    if (n == 0)
        fatal_error("ERROR: Path is empty");

    if (snprintf(out, out_size, "%s%s", SD_PREFIX, buf) >= (int)out_size)
        fatal_error("ERROR: Path too long");
}

static void read_core_name_from_romfs(const char *romfs_path, char *out, size_t out_size)
{
    FILE *f = fopen(romfs_path, "rb");
    if (!f)
        fatal_error("ERROR: Cannot open %s", romfs_path);

    char buf[CORE_NAME_MAXLEN];
    size_t n = fread(buf, 1, sizeof(buf) - 1, f);
    fclose(f);

    if (n == 0)
        fatal_error("ERROR: File empty: %s", romfs_path);

    buf[n] = '\0';

    /* Trim whitespace and newlines */
    while (n > 0 && (buf[n-1] == '\n' || buf[n-1] == '\r' || buf[n-1] == ' '))
        buf[--n] = '\0';

    if (n == 0)
        fatal_error("ERROR: Core name is empty");

    if (snprintf(out, out_size, "%s", buf) >= (int)out_size)
        fatal_error("ERROR: Core name too long: %s", buf);
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

static int isCiaInstalled(u64 titleId, u16 version)
{
    u32 titlesToRetrieve;
    u32 titlesRetrieved;
    u64* titleIds;
    u32 titlesToCheck;
    AM_TitleEntry titleInfo;
    bool titleExists = false;
    
    Result failed = AM_GetTitleCount(MEDIATYPE_SD, &titlesToRetrieve);
    if (R_FAILED(failed))
        return -1;

    titleIds = malloc(titlesToRetrieve * sizeof(u64));
    if (!titleIds)
        return -1;

    failed = AM_GetTitleList(&titlesRetrieved, MEDIATYPE_SD, titlesToRetrieve, titleIds);
    if (R_FAILED(failed))
    {
        free(titleIds);
        return -1;
    }

    for (titlesToCheck = 0; titlesToCheck < titlesRetrieved; titlesToCheck++)
    {
        if (titleIds[titlesToCheck] == titleId)
        {
            titleExists = true;
            break;
        }
    }

    free(titleIds);

    if (titleExists)
    {
        failed = AM_GetTitleInfo(MEDIATYPE_SD, 1, &titleId, &titleInfo);
        if (R_FAILED(failed))
            return -1;

        if (titleInfo.version == version)
            return 1;
    }

    return 0;
}

static void __attribute__((unused)) deleteCia(u64 titleId)
{
    u64 currTitleId = 0;

    /* Do not delete if the titleid is currently running */
    if (R_FAILED(APT_GetAppletInfo((NS_APPID)envGetAptAppId(), &currTitleId, NULL, NULL, NULL, NULL)) 
        || titleId != currTitleId)
    {
        AM_DeleteTitle(MEDIATYPE_SD, titleId);
        AM_DeleteTicket(titleId);
    }
}

static int installCia(const char *ciaPath)
{
    struct stat sBuff;
    Handle ciaFile;
    FS_Archive ciaArchive;
    Handle outputHandle;
    u64 fileSize;
    u32 bytesRead;
    u32 bytesWritten;
    u8 transferBuffer[FILE_CHUNK_SIZE];
    u64 fileOffset = 0;

    if (stat(ciaPath, &sBuff) != 0)
    {
        printf("ERROR: CIA file not found: %s\n", ciaPath);
        return -1;
    }

    printf("Opening SD archive...\n");
    Result res = FSUSER_OpenArchive(&ciaArchive,
            ARCHIVE_SDMC, fsMakePath(PATH_EMPTY, ""));
    if (R_FAILED(res))
    {
        printf("ERROR: Cannot open SD archive (0x%08lX)\n", res);
        return -1;
    }

    printf("Opening CIA file: %s\n", ciaPath);
    /* Skip only "sdmc:" (5 chars), NOT "sdmc:/" (6): FSUSER needs the
     * leading slash in the path ("/retroarch/cores/xxx.cia"), just like
     * RetroArch's original ctr/exec_cia.c does (path + 5). Skipping the
     * slash makes FSUSER_OpenFile fail and aborts the whole install. */
    const char *relPath = ciaPath;
    if (strncmp(relPath, "sdmc:", 5) == 0)
        relPath += 5;

    res = FSUSER_OpenFile(&ciaFile, ciaArchive,
            fsMakePath(PATH_ASCII, relPath),
            FS_OPEN_READ, 0);
    if (R_FAILED(res))
    {
        printf("ERROR: Cannot open CIA file (0x%08lX)\n", res);
        FSUSER_CloseArchive(ciaArchive);
        return -1;
    }

    printf("Starting CIA install...\n");
    res = AM_StartCiaInstall(MEDIATYPE_SD, &outputHandle);
    if (R_FAILED(res))
    {
        printf("ERROR: Cannot start CIA install (0x%08lX)\n", res);
        FSFILE_Close(ciaFile);
        FSUSER_CloseArchive(ciaArchive);
        return -1;
    }

    res = FSFILE_GetSize(ciaFile, &fileSize);
    if (R_FAILED(res))
    {
        printf("ERROR: Cannot get CIA file size (0x%08lX)\n", res);
        AM_CancelCIAInstall(outputHandle);
        FSFILE_Close(ciaFile);
        FSUSER_CloseArchive(ciaArchive);
        return -1;
    }

    printf("Installing %llu bytes...\n", fileSize);

    while (fileOffset < fileSize)
    {
        u64 bytesRemaining = fileSize - fileOffset;
        u32 chunkSize = bytesRemaining < FILE_CHUNK_SIZE ? bytesRemaining : FILE_CHUNK_SIZE;

        res = FSFILE_Read(ciaFile, &bytesRead, fileOffset, transferBuffer, chunkSize);
        if (R_FAILED(res))
        {
            printf("ERROR: Read failed at offset %llu (0x%08lX)\n", fileOffset, res);
            AM_CancelCIAInstall(outputHandle);
            FSFILE_Close(ciaFile);
            FSUSER_CloseArchive(ciaArchive);
            return -1;
        }

        res = FSFILE_Write(outputHandle, &bytesWritten, fileOffset, transferBuffer, bytesRead, FS_WRITE_FLUSH);
        if (R_FAILED(res))
        {
            printf("ERROR: Write failed (0x%08lX)\n", res);
            AM_CancelCIAInstall(outputHandle);
            FSFILE_Close(ciaFile);
            FSUSER_CloseArchive(ciaArchive);
            if (R_DESCRIPTION(res) == RD_ALREADY_EXISTS)
                return 1; /* Already exists, that's ok */
            return -1;
        }

        printf("Progress: %llu / %llu\r", fileOffset, fileSize);
        fflush(stdout);

        if (bytesWritten != bytesRead)
        {
            printf("ERROR: Write mismatch\n");
            AM_CancelCIAInstall(outputHandle);
            FSFILE_Close(ciaFile);
            FSUSER_CloseArchive(ciaArchive);
            return -1;
        }

        fileOffset += bytesWritten;
    }

    printf("\nFinishing CIA install...\n");
    res = AM_FinishCiaInstall(outputHandle);
    if (R_FAILED(res))
    {
        printf("ERROR: Cannot finish CIA install (0x%08lX)\n", res);
        FSFILE_Close(ciaFile);
        FSUSER_CloseArchive(ciaArchive);
        return -1;
    }

    FSFILE_Close(ciaFile);
    FSUSER_CloseArchive(ciaArchive);

    printf("CIA installed successfully!\n");
    return 1;
}

int main(void)
{
    if (!gspHasGpuRight())
        gfxInitDefault();
    consoleInit(GFX_TOP, NULL);
    g_console_ready = true;

    printf("Loading paths...\n");

    Result rc = romfsInit();
    if (R_FAILED(rc))
        fatal_error("romfsInit failed");

    char core_name[CORE_NAME_MAXLEN];
    char content_path[MAX_PATH_LEN];
    char core_cia_path[MAX_PATH_LEN];

    /* Read config from RomFS: just the core name (libretro_name) and the
     * content path. Title ID and CIA path come from CORES_TABLE, generated
     * from cores.json (see cores_table.h). */
    read_core_name_from_romfs("romfs:/core.txt", core_name, sizeof(core_name));
    read_sd_path_from_romfs("romfs:/content.path", content_path, sizeof(content_path));

    romfsExit();

    const core_entry_t *core = lookup_core(core_name);
    if (!core)
        fatal_error("ERROR: Unknown core '%s'\n(is cores_table.h out of date?)", core_name);

    u64 core_title_id = core->title_id;
    if (snprintf(core_cia_path, sizeof(core_cia_path), "%s%s%s",
                 SD_PREFIX, CORES_SD_DIR, core->cia_filename) >= (int)sizeof(core_cia_path))
        fatal_error("ERROR: CIA path too long for core '%s'", core_name);

    printf("Core: %s\n", core_name);
    printf("Core Title ID: 0x%016llX\n", core_title_id);
    printf("Core CIA: %s\n", core_cia_path);
    printf("Content: %s\n\n", content_path);

    /* Initialize AM (Application Manager) and FS */
    printf("Initializing services...\n");
    if (R_FAILED(amInit()) || R_FAILED(fsInit()))
        fatal_error("Cannot initialize AM/FS services");

    /* Check if core CIA is installed */
    printf("Checking if core is installed...\n");
    int ciaInstalled = isCiaInstalled(core_title_id, 0);
    if (ciaInstalled == -1)
    {
        fatal_error("ERROR: Could not read title list");
    }
    else if (ciaInstalled == 0)
    {
        printf("Core not installed, installing...\n");
        int installResult = installCia(core_cia_path);
        if (installResult == -1)
        {
            amExit();
            fsExit();
            fatal_error("ERROR: CIA installation failed");
        }
    }
    else
    {
        printf("Core already installed!\n");
    }

    /* Build argument buffer for RetroArch */
    printf("Preparing arguments...\n");
    ciaParam param;
    param.argc = 0;
    int argsLength = 0;
    char *argLocation = param.args;

    /* argv[0]: "program" name (RetroArch ignores it, but it must be
     * present: the content goes in argv[1], not argv[0] -- this matches
     * RetroArch's original ctr/exec-3dsx/exec_cia.c. Without this "filler"
     * argv[0], RetroArch starts up without detecting any ROM). */
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

    printf("Arguments ready (argc=%lu)\n", (unsigned long)param.argc);

    /* Prepare and execute the jump to the core */
    printf("Preparing application jump to core...\n");
    Result res = APT_PrepareToDoApplicationJump(0, core_title_id, 0x1);
    if (R_FAILED(res))
    {
        amExit();
        fsExit();
        fatal_error("ERROR: Cannot prepare jump (0x%08lX)", res);
    }

    printf("Executing jump to core...\n");
    res = APT_DoApplicationJump(&param, sizeof(param.argc) + argsLength, argvHmac);
    if (R_FAILED(res))
    {
        amExit();
        fsExit();
        fatal_error("ERROR: Cannot execute jump (0x%08lX)", res);
    }

    /* Should never reach here */
    amExit();
    fsExit();
    gfxExit();
    return 0;
}
