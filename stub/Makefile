#---------------------------------------------------------------------------------
# Adapted from devkitPro's OFFICIAL Makefile (devkitPro/3ds-examples repo,
# "romfs" example), checked line by line against the original rather than
# written from memory. Only TARGET/ICON/APP_* were changed, and the graphics
# bits (GRAPHICS/GFXBUILD/t3s) were dropped since this project doesn't use them.
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

# Path to the shared Python tooling, one level up from this Makefile.
TOOLS_DIR	:=	$(TOPDIR)/../tools

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
# CIA packaging (installed with FBI instead of run as a loose .3dsx via
# Homebrew Launcher). See forwarder.rsf for the reasoning.
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
# Placeholder assets (icon.png / banner.png / audio.wav): only generated if
# missing, so dropping in real artwork under the same names never gets
# overwritten.
#---------------------------------------------------------------------------------
icon.png banner.png audio.wav:
	python3 $(TOOLS_DIR)/generate_placeholder_assets.py --out-dir $(TOPDIR)

icon.icn: icon.png
	@# "-f visible,recordusage": without "visible" the title installs and
	@# even launches from FBI, but the HOME Menu won't list it (FBI lists
	@# everything installed regardless of this flag).
	$(BANNERTOOL) makesmdh -i icon.png -s "$(APP_TITLE)" -l "$(APP_DESCRIPTION)" \
		-p "$(APP_AUTHOR)" -f visible,recordusage -o icon.icn

banner.bnr: banner.png audio.wav
	$(BANNERTOOL) makebanner -i banner.png -a audio.wav -o banner.bnr

#---------------------------------------------------------------------------------
# .cia: first ensures the .elf (target 'all', which builds the .3dsx along
# the way), then packages it with makerom using that same .elf + RomFS +
# icon/banner + forwarder.rsf.
#---------------------------------------------------------------------------------
.PHONY: cia
cia: all icon.icn banner.bnr
	@# The RomFS is NOT passed on the CLI: it is already set in
	@# forwarder.rsf (RomFs: RootPath: romfs), makerom reads it from there.
	$(MAKEROM) -f cia -o $(TARGET).cia -rsf $(RSF) -target t -exefslogo \
		-elf $(OUTPUT).elf -icon icon.icn -banner banner.bnr
	@echo "--------------------------------------------------------------"
	@echo " CIA generated: $(TARGET).cia -- install it with FBI"
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
