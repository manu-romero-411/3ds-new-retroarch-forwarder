// 3ds-new-forwarder-generator — stub de forwarder
//
// Este binario se compila UNA sola vez. Lo que cambia entre forwarders
// es únicamente el contenido de su RomFS (core.path / content.path),
// no el .3dsx en sí. El backend, por cada juego, genera una RomFS
// nueva y reempaqueta este mismo ELF en un .cia distinto con makerom.
//
// Flujo:
//   1. Montar la RomFS propia del forwarder.
//   2. Leer romfs:/core.path y romfs:/content.path (rutas relativas
//      a la raíz de la SD, sin barra inicial, codificadas en UTF-8,
//      SIN salto de línea final).
//   3. Construir las rutas absolutas "sdmc:/..." correspondientes.
//   4. Saltar al .3dsx del core pasándole la ruta del contenido como
//      argv[1] (que es como RetroArch espera recibir la ROM cuando
//      ya lleva el core embebido — ver conversación previa).
//   5. Si algo falla en cualquier punto, NO debe haber una pantalla
//      negra sin explicación: se muestra el error en la pantalla
//      superior y se espera a START para salir limpiamente.

#include <3ds.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SD_PREFIX        "sdmc:/"
#define MAX_PATH_LEN     512

// ---------------------------------------------------------------------
// Utilidades de consola / error, para no dejar nunca una pantalla negra
// muda si algo va mal. Esto sí es boilerplate estándar de ctrulib.
// ---------------------------------------------------------------------

static void fatal_error(const char *fmt, ...)
{
    gfxInitDefault();
    consoleInit(GFX_TOP, NULL);

    va_list args;
    va_start(args, fmt);
    vprintf(fmt, args);
    va_end(args);

    printf("\n\nPulsa START para salir.\n");

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

// ---------------------------------------------------------------------
// Lectura de un fichero de texto plano desde la RomFS del propio
// forwarder. Devuelve la ruta ABSOLUTA de SD ya construida
// (prefijo "sdmc:/" + contenido del fichero).
// ---------------------------------------------------------------------

static void read_sd_path_from_romfs(const char *romfs_path, char *out, size_t out_size)
{
    FILE *f = fopen(romfs_path, "rb");
    if (!f)
        fatal_error("No se pudo abrir %s dentro de la RomFS.\n"
                    "El forwarder esta mal empaquetado.", romfs_path);

    char buf[MAX_PATH_LEN];
    size_t n = fread(buf, 1, sizeof(buf) - 1, f);
    fclose(f);

    if (n == 0)
        fatal_error("%s esta vacio.\nEl forwarder esta mal empaquetado.", romfs_path);

    buf[n] = '\0';

    // Por si el generador ha dejado un salto de linea al escribir el fichero
    char *nl = strpbrk(buf, "\r\n");
    if (nl) *nl = '\0';

    if (snprintf(out, out_size, "%s%s", SD_PREFIX, buf) >= (int)out_size)
        fatal_error("Ruta demasiado larga:\n%s%s", SD_PREFIX, buf);
}

// ---------------------------------------------------------------------
// *** PIEZA PENDIENTE DE PORTAR ***
//
// Esto NO esta implementado todavia a proposito. El contrato que tiene
// que cumplir, una vez lo portemos de RetroArch (ctr/exec-3dsx/exec_3dsx.c
// + mini-hb-menu/loaders/rosalina.c) o de new-hbmenu, es:
//
//   - Recibe la ruta absoluta de SD del .3dsx del core (target_3dsx_path)
//     y la ruta absoluta de SD del contenido (content_path).
//   - Bajo Luma3DS/Rosalina, solicita al loader la carga de
//     target_3dsx_path en sustitucion del proceso actual, pasandole
//     un unico argumento: content_path.
//   - Si la funcion vuelve, es que ha fallado (un salto exitoso no
//     retorna: el proceso pasa a ser el del core). Por eso el "return"
//     de aqui simplemente esta para poder compilar y probar el resto
//     del flujo (lectura de romfs, construccion de rutas) antes de
//     tener el loader real.
// ---------------------------------------------------------------------

static bool load_and_jump_to_3dsx(const char *target_3dsx_path, const char *content_path)
{
    (void)target_3dsx_path;
    (void)content_path;

    // TODO_PORT: sustituir este cuerpo por la implementacion real,
    // adaptada de exec_3dsx.c / rosalina.c de RetroArch.
    return false;
}

// ---------------------------------------------------------------------

int main(void)
{
    Result rc = romfsInit();
    if (R_FAILED(rc))
        fatal_error("romfsInit() fallo: 0x%08lX", rc);

    char core_path[MAX_PATH_LEN];
    char content_path[MAX_PATH_LEN];

    read_sd_path_from_romfs("romfs:/core.path", core_path, sizeof(core_path));
    read_sd_path_from_romfs("romfs:/content.path", content_path, sizeof(content_path));

    romfsExit();

    // A partir de aqui ya no necesitamos nuestra propia RomFS: las rutas
    // ya estan copiadas a variables locales en RAM.

    if (!load_and_jump_to_3dsx(core_path, content_path))
    {
        fatal_error("No se pudo cargar el core.\n\nCore:\n%s\n\nContenido:\n%s",
                    core_path, content_path);
    }

    // Si el salto tiene exito, esta linea nunca se ejecuta.
    return 0;
}
