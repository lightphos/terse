#
for c in 25 50; do
  echo "BLOCKING c=$c"
  ab -n 2000 -c "$c" http://127.0.0.1:8765/api | tee "blocking-c$c.txt" &

  echo "NON-BLOCKING c=$c"
  ab -n 2000 -c "$c" http://127.0.0.1:8766/api | tee "nonblocking-c$c.txt"
done
