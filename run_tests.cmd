@echo off
cd /d D:\oco
python -m unittest discover -s tests -t . 1>out.txt 2>&1
findstr /C:"Ran " out.txt
findstr /R /C:"^OK" out.txt
findstr /C:"FAILED" out.txt
