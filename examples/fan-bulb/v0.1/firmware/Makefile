CC ?= cc
CFLAGS ?= -std=c11 -Wall -Wextra -Werror -O2

.PHONY: test clean

test: build/test_light
	./build/test_light

build/test_light: src/light.c src/light.h tests/test_light.c
	mkdir -p build
	$(CC) $(CFLAGS) -Isrc src/light.c tests/test_light.c -lm -o $@

clean:
	rm -rf build
