CC ?= cc
CFLAGS ?= -std=c11 -Wall -Wextra -Werror -O2

.PHONY: test clean

test: build/test_strip
	./build/test_strip

build/test_strip: src/strip.c src/strip.h tests/test_strip.c
	mkdir -p build
	$(CC) $(CFLAGS) -Isrc src/strip.c tests/test_strip.c -lm -o $@

clean:
	rm -rf build
