/* AUTO-GENERADO por generate_cores_table.py a partir de cores.json.
 * NO EDITAR A MANO. Para actualizar tras un cambio en RetroArch:
 *
 *   python3 parse_retroarch_cores.py <RetroArch>/pkg/ctr/Makefile.cores > cores.json
 *   python3 generate_cores_table.py cores.json > source/cores_table.h
 *
 * Total de cores: 115
 */
#ifndef _CORES_TABLE_H_
#define _CORES_TABLE_H_

#include <3ds/types.h>

typedef struct {
    const char *libretro_name;
    u64 title_id;
    const char *cia_filename;
} core_entry_t;

static const core_entry_t CORES_TABLE[] = {
    { "2048", 0x000400000BAC0B00ULL, "2048_libretro.cia" }, /* 2048 Libretro */
    { "81", 0x000400000BAC1E00ULL, "81_libretro.cia" }, /* lr-81 */
    { "a5200", 0x000400000BACD700ULL, "a5200_libretro.cia" }, /* a5200 */
    { "anarch", 0x000400000BACE500ULL, "anarch_libretro.cia" }, /* Anarch */
    { "ardens", 0x000400000BACE600ULL, "ardens_libretro.cia" }, /* Ardens */
    { "arduous", 0x000400000BACD800ULL, "arduous_libretro.cia" }, /* Arduous */
    { "atari800", 0x000400000BAC9E00ULL, "atari800_libretro.cia" }, /* Atari800 */
    { "bk", 0x000400000BAC9B00ULL, "bk_libretro.cia" }, /* BK 0010/0011 */
    { "bluemsx", 0x000400000BAC9A00ULL, "bluemsx_libretro.cia" }, /* blueMSX */
    { "cap32", 0x000400000BAC3E00ULL, "cap32_libretro.cia" }, /* Caprice32 */
    { "chailove", 0x000400000BACB200ULL, "chailove_libretro.cia" }, /* ChaiLove */
    { "crocods", 0x000400000BACB400ULL, "crocods_libretro.cia" }, /* CROCODS */
    { "dice", 0x000400000BACE700ULL, "dice_libretro.cia" }, /* Dice */
    { "dosbox", 0x000400000BAC1B00ULL, "dosbox_libretro.cia" }, /* DosBox */
    { "dosbox_svn", 0x000400000BAC3F00ULL, "dosbox_svn_libretro.cia" }, /* DosBox SVN */
    { "doublecherrygb", 0x000400000BACE800ULL, "doublecherrygb_libretro.cia" }, /* DoubleCherryGB */
    { "ecwolf", 0x000400000BAC9600ULL, "ecwolf_libretro.cia" }, /* ECWolf */
    { "fbalpha2012", 0x000400000BAC1700ULL, "fbalpha2012_libretro.cia" }, /* Final Burn Alpha 2012 */
    { "fbalpha2012_cps1", 0x000400000BAC1100ULL, "fbalpha2012_cps1_libretro.cia" }, /* Final Burn Alpha 2012 - CPS-1 */
    { "fbalpha2012_cps2", 0x000400000BAC1200ULL, "fbalpha2012_cps2_libretro.cia" }, /* Final Burn Alpha 2012 - CPS-2 */
    { "fbalpha2012_cps3", 0x000400000BAC9200ULL, "fbalpha2012_cps3_libretro.cia" }, /* Final Burn Alpha 2012 - CPS-3 */
    { "fbalpha2012_neogeo", 0x000400000BAC1000ULL, "fbalpha2012_neogeo_libretro.cia" }, /* Final Burn Alpha 2012 - NeoGeo */
    { "fbneo", 0x000400000BAC9300ULL, "fbneo_libretro.cia" }, /* FinalBurn Neo */
    { "fbneo_cps12", 0x000400000BACE900ULL, "fbneo_cps12_libretro.cia" }, /* FinalBurn Neo CPS-1 / CPS-2 */
    { "fbneo_neogeo", 0x000400000BACEA00ULL, "fbneo_neogeo_libretro.cia" }, /* FinalBurn Neo Neo-Geo */
    { "fceumm", 0x000400000BAC0300ULL, "fceumm_libretro.cia" }, /* FCeumm Libretro */
    { "ffmpeg", 0x000400000BAC9D00ULL, "ffmpeg_libretro.cia" }, /* FFMPEG */
    { "fmsx", 0x000400000BAC1600ULL, "fmsx_libretro.cia" }, /* fMSX */
    { "freechaf", 0x000400000BAC9C00ULL, "freechaf_libretro.cia" }, /* FreeChaf */
    { "freeintv", 0x000400000BAC2100ULL, "freeintv_libretro.cia" }, /* FreeIntv */
    { "frodo", 0x000400000BACB900ULL, "frodo_libretro.cia" }, /* Frodo */
    { "fuse", 0x000400000BAC1F00ULL, "fuse_libretro.cia" }, /* Fuse */
    { "gambatte", 0x000400000BAC0100ULL, "gambatte_libretro.cia" }, /* Gambatte Libretro */
    { "gearboy", 0x000400000BACD400ULL, "gearboy_libretro.cia" }, /* Gearboy */
    { "gearcoleco", 0x000400000BACD500ULL, "gearcoleco_libretro.cia" }, /* Gearcoleco */
    { "gearsystem", 0x000400000BACD600ULL, "gearsystem_libretro.cia" }, /* gearsystem */
    { "genesis_plus_gx", 0x000400000BAC0600ULL, "genesis_plus_gx_libretro.cia" }, /* Genesis Plus GX Libretro */
    { "genesis_plus_gx_wide", 0x000400000BACE000ULL, "genesis_plus_gx_wide_libretro.cia" }, /* Genesis Plus GX Libretro Wide */
    { "gme", 0x000400000BACA800ULL, "gme_libretro.cia" }, /* GME */
    { "gong", 0x000400000BACD900ULL, "gong_libretro.cia" }, /* Gong */
    { "gpsp", 0x000400000BAC0200ULL, "gpsp_libretro.cia" }, /* gpSP Libretro */
    { "gw", 0x000400000BAC2D00ULL, "gw_libretro.cia" }, /* Game&Watch Libretro */
    { "handy", 0x000400000BAC7C00ULL, "handy_libretro.cia" }, /* Handy Libretro */
    { "hatari", 0x000400000BACAD00ULL, "hatari_libretro.cia" }, /* Hatari */
    { "jaxe", 0x000400000BACE200ULL, "jaxe_libretro.cia" }, /* jaxe */
    { "jumpnbump", 0x000400000BACDA00ULL, "jumpnbump_libretro.cia" }, /* Jump'n Bump */
    { "lowresnx", 0x000400000BACD100ULL, "lowresnx_libretro.cia" }, /* LowRes NX */
    { "lutro", 0x000400000BACAF00ULL, "lutro_libretro.cia" }, /* Lutro */
    { "mame2000", 0x000400000BAC1900ULL, "mame2000_libretro.cia" }, /* MAME-2000 */
    { "mame2003", 0x000400000BAC1800ULL, "mame2003_libretro.cia" }, /* MAME-2003 */
    { "mame2003_plus", 0x000400000BAC2200ULL, "mame2003_plus_libretro.cia" }, /* MAME-2003-PLUS */
    { "mednafen_ngp", 0x000400000BAC0A00ULL, "mednafen_ngp_libretro.cia" }, /* Mednafen NGP Libretro */
    { "mednafen_pce_fast", 0x000400000BAC1400ULL, "mednafen_pce_fast_libretro.cia" }, /* Mednafen/Beetle PCE FAST */
    { "mednafen_vb", 0x000400000BAC0900ULL, "mednafen_vb_libretro.cia" }, /* Mednafen VB Libretro */
    { "mednafen_wswan", 0x000400000BAC0800ULL, "mednafen_wswan_libretro.cia" }, /* Mednafen wswan Libretro */
    { "mgba", 0x000400000BAC0E00ULL, "mgba_libretro.cia" }, /* mGBA Libretro */
    { "minivmac", 0x000400000BACDB00ULL, "minivmac_libretro.cia" }, /* Mini vMac */
    { "mrboom", 0x000400000BACA600ULL, "mrboom_libretro.cia" }, /* MrBoom */
    { "mu", 0x000400000BAC2F00ULL, "mu_libretro.cia" }, /* Mu Palm Emulator */
    { "nekop2", 0x000400000BAC1C00ULL, "nekop2_libretro.cia" }, /* Neko Project 2 */
    { "neocd", 0x000400000BACB600ULL, "neocd_libretro.cia" }, /* NeoCD */
    { "nestopia", 0x000400000BAC0400ULL, "nestopia_libretro.cia" }, /* Nestopia Libretro */
    { "np2kai", 0x000400000BAC1D00ULL, "np2kai_libretro.cia" }, /* Neko Project 2 Kai */
    { "numero", 0x000400000BACEB00ULL, "numero_libretro.cia" }, /* Numero */
    { "nxengine", 0x000400000BAC0500ULL, "nxengine_libretro.cia" }, /* NXengine Libretro */
    { "o2em", 0x000400000BAC8C00ULL, "o2em_libretro.cia" }, /* O2EM Libretro */
    { "opera", 0x000400000BAC9100ULL, "opera_libretro.cia" }, /* Opera */
    { "pcsx_rearmed", 0x000400000BAC1500ULL, "pcsx_rearmed_libretro.cia" }, /* PCSX ReARMed */
    { "picodrive", 0x000400000BAC0C00ULL, "picodrive_libretro.cia" }, /* Picodrive Libretro */
    { "pocketcdg", 0x000400000BACAC00ULL, "pocketcdg_libretro.cia" }, /* PocketCDG */
    { "pokemini", 0x000400000BAC2000ULL, "pokemini_libretro.cia" }, /* PokeMini */
    { "potator", 0x000400000BACD000ULL, "potator_libretro.cia" }, /* Potator */
    { "prboom", 0x000400000BAC9000ULL, "prboom_libretro.cia" }, /* PrBoom */
    { "prosystem", 0x000400000BAC3C00ULL, "prosystem_libretro.cia" }, /* ProSystem Libretro */
    { "quasi88", 0x000400000BAC4100ULL, "quasi88_libretro.cia" }, /* Quasi88 Libretro */
    { "quicknes", 0x000400000BAC0F00ULL, "quicknes_libretro.cia" }, /* QuickNES Libretro */
    { "race", 0x000400000BAC9500ULL, "race_libretro.cia" }, /* RACE */
    { "retro8", 0x000400000BACDC00ULL, "retro8_libretro.cia" }, /* RETRO-8 */
    { "scummvm", 0x000400000BACC000ULL, "scummvm_libretro.cia" }, /* ScummVM Libretro */
    { "smsplus", 0x000400000BAC9700ULL, "smsplus_libretro.cia" }, /* SMSplus */
    { "snes9x", 0x000400000BACBA00ULL, "snes9x_libretro.cia" }, /* Snes9x */
    { "snes9x2002", 0x000400000BAC1A00ULL, "snes9x2002_libretro.cia" }, /* Snes9x 2002 */
    { "snes9x2005", 0x000400000BAC0700ULL, "snes9x2005_libretro.cia" }, /* Snes9x 2005 */
    { "snes9x2005_plus", 0x000400000BAC1300ULL, "snes9x2005_plus_libretro.cia" }, /* Snes9x 2005 Plus */
    { "snes9x2010", 0x000400000BAC0D00ULL, "snes9x2010_libretro.cia" }, /* Snes9x 2010 */
    { "squirreljme", 0x000400000BAC9400ULL, "squirreljme_libretro.cia" }, /* SquirrelJME */
    { "stella", 0x000400000BAC3D00ULL, "stella_libretro.cia" }, /* Stella Libretro */
    { "stella2014", 0x000400000BAC2C00ULL, "stella2014_libretro.cia" }, /* Stella2014 Libretro */
    { "superbroswar", 0x000400000BACDD00ULL, "superbroswar_libretro.cia" }, /* Super Mario War */
    { "tamalibretro", 0x000400000BACEC00ULL, "tamalibretro_libretro.cia" }, /* TamaLIBretro */
    { "tgbdual", 0x000400000BACB800ULL, "tgbdual_libretro.cia" }, /* TGB-Dual */
    { "theodore", 0x000400000BAC2E00ULL, "theodore_libretro.cia" }, /* Theodore */
    { "thepowdertoy", 0x000400000BACB500ULL, "thepowdertoy_libretro.cia" }, /* ThePowderToy */
    { "tic80", 0x000400000BACB000ULL, "tic80_libretro.cia" }, /* TIC-80 */
    { "tyrquake", 0x000400000BACAA00ULL, "tyrquake_libretro.cia" }, /* Tyrquake */
    { "uw8", 0x000400000BACED00ULL, "uw8_libretro.cia" }, /* MicroW8 */
    { "uzem", 0x000400000BACB700ULL, "uzem_libretro.cia" }, /* Uzem */
    { "vaporspec", 0x000400000BACDE00ULL, "vaporspec_libretro.cia" }, /* Vapor Spec */
    { "vecx", 0x000400000BAC4C00ULL, "vecx_libretro.cia" }, /* VecX Libretro */
    { "vice_x128", 0x000400000BACA100ULL, "vice_x128_libretro.cia" }, /* VICE x128 */
    { "vice_x64", 0x000400000BAC9F00ULL, "vice_x64_libretro.cia" }, /* VICE x64 */
    { "vice_x64sc", 0x000400000BACA000ULL, "vice_x64sc_libretro.cia" }, /* VICE x64sc */
    { "vice_xcbm2", 0x000400000BACA200ULL, "vice_xcbm2_libretro.cia" }, /* VICE xcbm2 */
    { "vice_xcbm5x0", 0x000400000BACD200ULL, "vice_xcbm5x0_libretro.cia" }, /* VICE xcbm5x0 */
    { "vice_xpet", 0x000400000BACA300ULL, "vice_xpet_libretro.cia" }, /* VICE xpet */
    { "vice_xplus4", 0x000400000BACA400ULL, "vice_xplus4_libretro.cia" }, /* VICE xplus4 */
    { "vice_xscpu64", 0x000400000BACD300ULL, "vice_xscpu64_libretro.cia" }, /* VICE xscpu64 */
    { "vice_xvic", 0x000400000BACA500ULL, "vice_xvic_libretro.cia" }, /* VICE xvic */
    { "vitaquake2", 0x000400000BAC9800ULL, "vitaquake2_libretro.cia" }, /* vitaquake2 */
    { "vitaquake2-rogue", 0x000400000BACDF00ULL, "vitaquake2-rogue_libretro.cia" }, /* vitaquake2-rogue */
    { "vitaquake2-xatrix", 0x000400000BACE300ULL, "vitaquake2-xatrix_libretro.cia" }, /* vitaquake2-xatrix */
    { "vitaquake2-zaero", 0x000400000BACE400ULL, "vitaquake2-zaero_libretro.cia" }, /* vitaquake2-zaero */
    { "wasm4", 0x000400000BACE100ULL, "wasm4_libretro.cia" }, /* wasm4 */
    { "x1", 0x000400000BAC9900ULL, "x1_libretro.cia" }, /* XMillenium Libretro */
    { "xrick", 0x000400000BACA900ULL, "xrick_libretro.cia" }, /* XRick */
};

#define CORES_TABLE_COUNT (sizeof(CORES_TABLE) / sizeof(CORES_TABLE[0]))

#endif /* _CORES_TABLE_H_ */

