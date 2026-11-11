; A x B by repeated addition. A is input bits 7 to 4, B is input bits 3 to 0.
;
;   input 0x67: 6 x 7 = 42
;   input 0xFF: 15 x 15 = 225, the largest product

a       = r0
b       = r1
product = r2
raw     = r3

        IN
        ST   raw
        AND  #0x0F
        ST   b
        LD   raw
        SHR
        SHR
        SHR
        SHR
        ST   a
        LD   #0
        ST   product
loop:   LD   b
        JZ   done           ; B additions made
        SUB  #1
        ST   b
        LD   product
        ADD  a
        ST   product
        JMP  loop
done:   LD   product
        OUT
        HLT
