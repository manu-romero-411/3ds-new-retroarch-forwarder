#---------------------------------------------------------------------------------
# Adaptado del Makefile OFICIAL de devkitPro (repo devkitPro/3ds-examples,
# ejemplo "romfs"), verificado línea a línea contra el original en vez de
# escrito de memoria. Solo se han cambiado TARGET/ICON/APP_* y quitado lo
# de gráficos (GRAPHICS/GFXBUILD/t3s), que no usamos.
#---------------------------------------------------------------------------------
.SUFFIXES:
#---------------------------------------------------------------------------------

ifeq ($(strip $(DEVKITARM)),)
$(error "Please set DEVKITARM in your environment. export DEVKITARM=<path to>devkitARM")
endif

TOPDIR ?= $(CURDIR)
include $(DEVKITARM)/3ds_rules

#---------------------------------------------------------------------------------
TARGET		:=	3ds-forwarder-stub
BUILD		:=	build
SOURCES		:=	source
DATA		:=	data
INCLUDES	:=	include
ROMFS		:=	romfs

APP_TITLE       := Forwarder
APP_DESCRIPTION := 3ds-new-forwarder-generator stub
APP_AUTHOR      := Manu

#---------------------------------------------------------------------------------
ARCH	:=	-march=armv6k -mtune=mpcore -mfloat-abi=hard -mtp=soft

CFLAGS	:=	-g -Wall -O2 -mword-relocations \
			-ffunction-sections \
			$(ARCH)

CFLAGS	+=	$(INCLUDE) -D__3DS__

CXXFLAGS	:= $(CFLAGS) -fno-rtti -fno-exceptions -std=gnu++11

ASFLAGS	:=	-g $(ARCH)
LDFLAGS	=	-specs=3dsx.specs -g $(ARCH) -Wl,-Map,$(notdir $*.map)

LIBS	:= -lctru -lm

LIBDIRS	:= $(CTRULIB)

#---------------------------------------------------------------------------------
# Empaquetado como CIA (para instalar con FBI en vez de correr como .3dsx
# suelto vía Homebrew Launcher). Ver forwarder.rsf para el porqué.
#---------------------------------------------------------------------------------
BANNERTOOL	?=	bannertool
MAKEROM		?=	makerom
RSF			:=	forwarder.rsf

#---------------------------------------------------------------------------------
ifneq ($(BUILD),$(notdir $(CURDIR)))
#---------------------------------------------------------------------------------

export OUTPUT	:=	$(CURDIR)/$(TARGET)
export TOPDIR	:=	$(CURDIR)

export VPATH	:=	$(foreach dir,$(SOURCES),$(CURDIR)/$(dir)) \
			$(foreach dir,$(DATA),$(CURDIR)/$(dir))

export DEPSDIR	:=	$(CURDIR)/$(BUILD)

CFILES		:=	$(foreach dir,$(SOURCES),$(notdir $(wildcard $(dir)/*.c)))
CPPFILES	:=	$(foreach dir,$(SOURCES),$(notdir $(wildcard $(dir)/*.cpp)))
SFILES		:=	$(foreach dir,$(SOURCES),$(notdir $(wildcard $(dir)/*.s)))
BINFILES	:=	$(foreach dir,$(DATA),$(notdir $(wildcard $(dir)/*.*)))

#---------------------------------------------------------------------------------
ifeq ($(strip $(CPPFILES)),)
#---------------------------------------------------------------------------------
	export LD	:=	$(CC)
#---------------------------------------------------------------------------------
else
#---------------------------------------------------------------------------------
	export LD	:=	$(CXX)
#---------------------------------------------------------------------------------
endif
#---------------------------------------------------------------------------------

export OFILES_SOURCES 	:=	$(CPPFILES:.cpp=.o) $(CFILES:.c=.o) $(SFILES:.s=.o)

export OFILES_BIN	:=	$(addsuffix .o,$(BINFILES))

export OFILES := $(OFILES_BIN) $(OFILES_SOURCES)

export HFILES	:=	$(addsuffix .h,$(subst .,_,$(BINFILES)))

export INCLUDE	:=	$(foreach dir,$(INCLUDES),-I$(CURDIR)/$(dir)) \
			$(foreach dir,$(LIBDIRS),-I$(dir)/include) \
			-I$(CURDIR)/$(BUILD)

export LIBPATHS	:=	$(foreach dir,$(LIBDIRS),-L$(dir)/lib)

export _3DSXDEPS	:=	$(if $(NO_SMDH),,$(OUTPUT).smdh)

ifeq ($(strip $(ICON)),)
	icons := $(wildcard *.png)
	ifneq (,$(findstring $(TARGET).png,$(icons)))
		export APP_ICON := $(TOPDIR)/$(TARGET).png
	else
		ifneq (,$(findstring icon.png,$(icons)))
			export APP_ICON := $(TOPDIR)/icon.png
		endif
	endif
else
	export APP_ICON := $(TOPDIR)/$(ICON)
endif

ifeq ($(strip $(NO_SMDH)),)
	export _3DSXFLAGS += --smdh=$(CURDIR)/$(TARGET).smdh
endif

ifneq ($(ROMFS),)
	export _3DSXFLAGS += --romfs=$(CURDIR)/$(ROMFS)
endif

.PHONY: all clean

#---------------------------------------------------------------------------------
all: $(BUILD) $(DEPSDIR)
	@$(MAKE) --no-print-directory -C $(BUILD) -f $(CURDIR)/Makefile

$(BUILD):
	@mkdir -p $@

ifneq ($(DEPSDIR),$(BUILD))
$(DEPSDIR):
	@mkdir -p $@
endif

#---------------------------------------------------------------------------------
clean:
	@echo clean ...
	@rm -fr $(BUILD) $(TARGET).3dsx $(OUTPUT).smdh $(TARGET).elf $(TARGET).cia \
		icon.icn banner.bnr icon.png banner.png audio.wav

#---------------------------------------------------------------------------------
# Assets placeholder (icon.png / banner.png / audio.wav): se generan solo si
# no existen ya, así que si más adelante pones arte propio con esos mismos
# nombres, no se pisa.
#---------------------------------------------------------------------------------
icon.png banner.png audio.wav:
	python3 $(TOPDIR)/tools/generate_placeholder_assets.py

icon.icn: icon.png
	@# "-f visible,recordusage": sin "visible" el título se instala e
	@# incluso arranca desde FBI, pero el HOME Menu no lo lista (FBI sí
	@# lista todo lo instalado, con o sin este flag).
	$(BANNERTOOL) makesmdh -i icon.png -s "$(APP_TITLE)" -l "$(APP_DESCRIPTION)" \
		-p "$(APP_AUTHOR)" -f visible,recordusage -o icon.icn

banner.bnr: banner.png audio.wav
	$(BANNERTOOL) makebanner -i banner.png -a audio.wav -o banner.bnr

#---------------------------------------------------------------------------------
# .cia: primero se asegura el .elf (target 'all', ya construye el .3dsx de
# paso) y después empaqueta con makerom usando ese mismo .elf + el RomFS +
# icon/banner + forwarder.rsf.
#---------------------------------------------------------------------------------
.PHONY: cia
cia: all icon.icn banner.bnr
	@# El RomFS NO se pasa por CLI: ya está indicado en forwarder.rsf
	@# (RomFs: RootPath: romfs), makerom lo toma de ahí.
	$(MAKEROM) -f cia -o $(TARGET).cia -rsf $(RSF) -target t -exefslogo \
		-elf $(OUTPUT).elf -icon icon.icn -banner banner.bnr
	@echo "--------------------------------------------------------------"
	@echo " CIA generado: $(TARGET).cia -- instalalo con FBI"
	@echo "--------------------------------------------------------------"

#---------------------------------------------------------------------------------
else

#---------------------------------------------------------------------------------
$(OUTPUT).3dsx	:	$(OUTPUT).elf $(_3DSXDEPS)

$(OFILES_SOURCES) : $(HFILES)

$(OUTPUT).elf	:	$(OFILES)

#---------------------------------------------------------------------------------
%.bin.o	%_bin.h :	%.bin
#---------------------------------------------------------------------------------
	@echo $(notdir $<)
	@$(bin2o)

-include $(DEPSDIR)/*.d

#---------------------------------------------------------------------------------------
endif
#---------------------------------------------------------------------------------------
