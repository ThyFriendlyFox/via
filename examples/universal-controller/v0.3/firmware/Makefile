CC ?= cc
CFLAGS ?= -std=c11 -Wall -Wextra -Werror -O2

.PHONY: test clean

test: build/test_mode build/test_turbo build/test_charger
	./build/test_mode
	./build/test_turbo
	./build/test_charger

build/test_mode: src/mode.c src/mode.h tests/test_mode.c
	mkdir -p build
	$(CC) $(CFLAGS) -Isrc src/mode.c tests/test_mode.c -o $@

build/test_turbo: src/turbo.c src/turbo.h tests/test_turbo.c
	mkdir -p build
	$(CC) $(CFLAGS) -Isrc src/turbo.c tests/test_turbo.c -o $@

build/test_charger: src/charger.c src/charger.h tests/test_charger.c
	mkdir -p build
	$(CC) $(CFLAGS) -Isrc src/charger.c tests/test_charger.c -o $@

clean:
	rm -rf build
