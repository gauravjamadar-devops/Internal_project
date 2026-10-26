#!/bin/bash

if [ $# -ne 2]; then 
  echo "please provide exactly two numbers as arguments"
  echo "usage : $0 <num1> <num2>"
  exit 1
fi

      num1= $1
      num2= $2

sum = $((num1 + num2))

echo "sum of $num1 and $num2 is : $sum"
