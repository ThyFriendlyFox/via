CC ?= cc
CFLAGS ?= -std=c11 -Wall -Wextra -Werror -O2

.PHONY: test clean

test: build/test_mode
	./build/test_mode

build/test_mode: src/mode.c src/mode.h tests/test_mode.c
	mkdir -p build
	$(CC) $(CFLAGS) -Isrc src/mode.c tests/test_mode.c -o $@

clean:
	rm -rf build
