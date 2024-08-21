# ssh-audit-excel
Python 3 script to convert ssh-audit JSON result files to XLSX

## Creating JSON Output Files

````
python3 ssh-audit.py -2 -jj 127.0.0.1 -p 22 > output.json
````

## Creating Excel File

````
python3 ssh-audit-excel.py -d <path-to-dir-with-json-files>
````

![image](https://github.com/user-attachments/assets/ba55eaff-85b2-41ae-9740-e1b7dba8d810)
