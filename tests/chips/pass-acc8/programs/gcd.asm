; Greatest common divisor of A and B by subtraction. A is input bits 7 to 4,
; B is input bits 3 to 0. With one of them 0, the answer is the other.
;
;   input 0xC8: gcd(12, 8): 12 - 8 = 4, 8 - 4 = 4, the answer is 4
;   input 0x90: gcd(9, 0) = 9

a   = r0
b   = r1
raw = r2

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
        JZ   zero           ; Z is still the last SHR's: A == 0
        LD   b
        JZ   zero
loop:   LD   a
        CMP  b
        JZ   done           ; A == B
        JC   less           ; A < B
        SUB  b
        ST   a
        JMP  loop
less:   LD   b
        SUB  a
        ST   b
        JMP  loop
zero:   LD   a
        OR   b
        ST   a
done:   LD   a
        OUT
        HLT
