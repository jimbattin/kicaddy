#!/bin/bash
# Extra checks: low-level (crossover) THD, 10 kHz square-wave step response (overshoot), quiescent spread vs temperature
cd "$(dirname "$0")"
base() { sed -e "s/^.param .*/.param RL=$1 POT=1.0 VPK=$2/" -e '/^.control/,$d' hpamp.cir; }
{ base 32 0.02; cat <<'EOC'
.control
tran 1u 60m 40m
fourier 1k v(hp)
.endc
.end
EOC
} > _a.cir
echo "--- 20 mVpk in, 32 ohm (crossover region) ---"; ngspice -b _a.cir 2>&1 | grep -o "THD: [0-9.e+-]* %"
{ base 32 0.2 | sed 's/SIN(0 {VPK} 1k)/PULSE(-0.2 0.2 0 100n 100n 50u 100u)/'; cat <<'EOC'
.control
tran 20n 10.2m 10m
meas tran vmax max v(hp) from=10.0m to=10.1m
meas tran vmin min v(hp) from=10.0m to=10.1m
meas tran vhi find v(hp) at=10.045m
meas tran vlo find v(hp) at=10.095m
let ov = 100*((vmax-vmin)/(vhi-vlo)-1)
print ov
.endc
.end
EOC
} > _b.cir
echo "--- 10 kHz square, 0.2 Vpk in, 32 ohm ---"; ngspice -b _b.cir 2>&1 | grep -E "^(vmax|vmin|vhi|vlo|ov) "
for T in 0 27 50; do
{ base 32 0.0; echo ".options temp=$T"; cat <<'EOC'
.control
op
print (v(e1)-v(out))/2.2
.endc
.end
EOC
} > _c.cir
echo "--- Iq at ${T} C: $(ngspice -b _c.cir 2>&1 | grep -E '^\(v' | awk '{print $3}') A"
done
rm -f _a.cir _b.cir _c.cir
