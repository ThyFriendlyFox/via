; Sum of 1 to N. N is the input port. Every partial sum goes to the output
; port, so the last output is the answer and N = 0 gives no output.
;
;   N = 10: 1 3 6 10 15 21 28 36 45 55, the answer is 55
;   N = 23: 276, which wraps to 276 - 256 = 20

n     = r0
i     = r1
total = r2

        IN
        ST   n
        LD   #0
        ST   i
        ST   total
loop:   LD   i
        CMP  n
        JZ   done           ; i == N: every term is in
        ADD  #1
        ST   i
        ADD  total
        ST   total
        OUT
        JMP  loop
done:   HLT
