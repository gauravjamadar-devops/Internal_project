#!/bin/bash
#echo "enter first number"
#read num1
#echo "enter second number"
#read num2
#sum=$((num1 + num2))
#sum=$((num1 + num2))
#echo "$sum"

if [ $# -ne 2 ] ; then 
  echo "provide exaactly 2 arguments" 
  echo "usage : $0 <<num1>> <<num2>>"
  exit 1
fi
num1=$1
num2=$2
sum=$((num1 + num2))
echo "sum of $num1 and $num2 is $sum"
