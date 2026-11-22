#!/bin/bash
# Transient THD/level sweep: RL x input peak (volume at max)
cd "$(dirname "$0")"
for RL in 16 32; do for VPK in 0.3 0.6 0.8 0.9 1.0; do
  sed -e "s/^.param .*/.param RL=$RL POT=1.0 VPK=$VPK/" -e '/^.control/,/^.endc/d' hpamp.cir > _t.cir
  sed -i '$d' _t.cir
  cat >> _t.cir <<EOC
.control
set noaskquit
tran 2u 60m 40m
fourier 1k v(hp)
meas tran vpk max v(hp) from=50m to=60m
meas tran ipk max i(VBAT) from=50m to=60m
.endc
.end
EOC
  out=$(ngspice -b _t.cir 2>&1)
  thd=$(grep -o "THD: [0-9.e+-]* %" <<<"$out")
  vpk=$(grep -E "^vpk " <<<"$out" | awk '{print $3}')
  printf "RL=%2s Vin_pk=%.1f  Vout_pk=%s  P=%s mW  %s\n" $RL $VPK $vpk $(python3 -c "print(round(1000*$vpk**2/2/$RL,1))") "$thd"
done; done
rm -f _t.cir
