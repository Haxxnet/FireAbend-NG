# Description 

This script will parse a JSON result file generated by shcheck and convert it to XSLX. 
  
An shcheck json file can be generated with the following command: 

````bash 
python3 shcheck.py -d -g -j -k --hfile webservices.txt > shcheck_results.json 
````

# Installation 

The script requires the python modules mentioned in requirements.txt. These can be installed with the following command: 

````bash 
pip3 install -r requirements.txt 
````

## Usage 
The script can be started with the following command: 
````bash 
python3 shcheck2excel -i shcheck_results.json 
````
  
The output file will be an Excel file showing the results of the audit. 

## Credits

Many thanks to [michiiii](https://github.com/michiiii) for this beautiful helper script <3
