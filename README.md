
#This is where CHris lives. 

## Prerequisites. 
+ OpenStudio 2.4.1 installed. 
+ Ruby 2.2.4 with bundler gem installed. 

# btap
This repository contains measures, scripts and sample projects to get your started using BTAP and OpenStudio
## 1. Clone this repository to your deskop. Ideally to c:\btap if you are on a windows machine. 
```git clone https://github.com/canmet-energy/btap```

## 2. Launch PAT and open the C:/btap/pat_projects/necb_national_prototype_scan project. 

## 3. Select the Building Types and climate files that you wish to generate. 

## 4. Go to the 






##Downloading results for Tableau. 
```
bundle exec ruby utilities/analysis_results_downloader.rb -t <OpenStudio Server web address> -p projects/necb-analysis.xlsx -z -a <analysis-id>
```
