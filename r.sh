

#!/bin/bash

#if [ $# -ne 2 ] ; then  
#  echo "error, provide exactly 2 arguments"
#  echo "usage: $@ <num1> <num2>"
#  exit 1
#fi
#num1=$1
#num2=$2
#sum=$((num1 + num2))
#echo "sum of $num1 and $num2 is $sum "

echo "enter num 1"
read num1
echo "enter num 2"
read num2
echo
sum=$(($num1+$num2))
echo "sum of $num1 and $num2 is $sum"

