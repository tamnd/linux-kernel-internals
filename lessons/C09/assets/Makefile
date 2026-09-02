# Build abba.ko against the kernel you are running.
#
#   make            build abba.ko
#   make load       load it and print the report it causes
#   make unload     take it back out
#   make clean      remove the build output
#
# You need the headers for your running kernel. On Debian and Ubuntu that is
# linux-headers-$(uname -r), on Fedora it is kernel-devel. Without CONFIG_PROVE_LOCKING in that
# kernel the module still builds and loads and nothing is reported, which is worth seeing once.

obj-m += abba.o

KDIR ?= /lib/modules/$(shell uname -r)/build
PWD := $(shell pwd)

all:
	$(MAKE) -C $(KDIR) M=$(PWD) modules

load: all
	sudo dmesg -C
	sudo insmod abba.ko
	dmesg

unload:
	sudo rmmod abba

clean:
	$(MAKE) -C $(KDIR) M=$(PWD) clean

.PHONY: all load unload clean
