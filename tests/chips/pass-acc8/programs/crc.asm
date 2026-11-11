; CRC-8 of the input byte: polynomial x^8 + x^2 + x + 1 (0x07), start value 0,
; most significant bit first.
;
;   input 0x80: 07 0e 1c 38 70 e0 c7 89, the answer is 0x89
;   input 0x01: 7 shifts, then the 1 leaves and 0x07 comes in: 0x07

crc  = r0
bits = r1

        IN
        ST   crc
        LD   #8
        ST   bits
loop:   LD   crc
        SHL                 ; C is the bit that left
        JNC  keep
        XOR  #0x07
keep:   ST   crc
        LD   bits
        SUB  #1
        ST   bits
        JNZ  loop
        LD   crc
        OUT
        HLT
