# Lark — the loop

Each pass judged the layout against the housing (`bulb.fit()`), the gates and the renders, and made
the next. The owner asked for 2 things during v0.1: make the design as compact as it can be to fit
the bulb, and grow it, or stack boards in more than 1 direction, where it cannot fit. This file is
what each pass found and what it changed, oldest first.

## v0.1

1. **The form.** A bulb that hangs base-up in a fan's light kit: an E26 base, a neck, a dome. 3
   boards in 2 directions: the driver standing in the neck and down into the base, an aluminum
   light disc lying across the top of the neck, and a mast standing in the dome at 90 degrees to the
   driver for the radio, the voice chip and the microphones. Tongues on the standing boards pass
   slots in the disc and solder to pads beside them, so no connector and no cable joins them. The
   housing's cavities and every part's height are in `bulb.py`, and `fit()` stops a design whose
   part leaves them or meets another board.
2. **The microphones move to a 4th board.** On the mast they faced sideways into the dome's air.
   The ear, a 15 mm disc under the dome's tip, puts both ports toward the room, each through a
   gasket to its own hole: the dome's air no longer stands between the room and the membrane.
3. **The microphones' temperature.** The first choices were end of life (ICS-43434, SPH0645) or
   rated to 70 C at 3.3 V (IM69D130, 100 C only under 3.0 V). A 3.0 V regulator for it had no
   maker's model that ngspice runs. The SPH0641LU4H-1 is rated -40 to 100 C from 1.62 to 3.6 V:
   it runs from the 3.3 V rail through a 47 ohm and 2.2 uF filter.
4. **The fit check finds its first faults.** A bulk capacitor on the driver's back pointed out of
   the base (a back-face part is mirrored), and the Hall switches stood 0.7 mm too near the wall.
   The round chokes were checked as their square boxes, too strict where the neck narrows: `fit()`
   now checks a round body at points round its circle (`ROUND`).
5. **A15 does not fit.** Each of the driver's 56 parts fit the A15's neck and base, but not
   together: the first layout had 36 courtyard overlaps and 14 through-hole pads under parts on the
   other face, and no free area. The housing grew to an A19 (60 x 108 mm, `SHAPE = "A19"`); every
   board grew with it.
6. **The driver goes to 4 layers.** On 2 layers, with 0.8 mm between the mains nets and the logic,
   the router left 26 links open in the base's 20 mm. In1 became a ground plane; In2 is for signals.
7. **The router and the plane.** The router never saw In1, so it joined every GND pad with tracks of
   its own: 37 links open. Each surface GND pad got its own via to the plane (`plane_vias`), and the
   router's file got In1 back as a power layer holding the GND plane, which also keeps GND's pads in
   the LinkSwitch's 0.8 mm class-pair rule: 20 open, 0 spacing errors.
8. **The bus capacitors at their corners.** The bus deck said both strings at full current, but its
   9.1 W was one string's worth, and nothing held the 2 strings to that. At the corners a capacitor
   at +20 % beside 2 at -20 % carried 48.4 mA against its 47 mA rating. The firmware now holds warm
   and cool together to 90 % of one string (`firmware/src/light.h`, `LARK_BUDGET`): 44.7 mA at the
   worst corner.
9. **The last links by hand.** The router left 20 links open in the LED channels and at the
   tongues. The HV tongue's pads stand 0.35 mm from the tongue's edge, under the HV class's 0.8
   mm, so the router starts no track from them. The controllers' VIN, CS and GATE sit at the cone's
   narrow edge. `hand_routes()` draws 94 segments and 23 vias on 20 nets, each from the board's
   pad list (P4 step 7); kicadgen's own via check moved 2 of them. Inside the board the mains nets
   now keep IPC-2221B's 0.2 mm for internal conductors. The route: 0 links open, 0 DRC errors.
