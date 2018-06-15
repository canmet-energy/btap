## Introduction
This document will go through the steps to perform a simulation on the BTAP Archetypes and obtain the results. This is a living document and the process WILL change as BTAP and OpenStudio updates it's feature set. 

## Requirements
* Windows 7 
* Installation of OS 2.4.1 or higher. 
* Installation of the git command line. 
* An Amazon AWS account and credential. Instructions to create a creditials are [here](https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-getting-started.html)

## Download this repository using Git
Download the git repository to your computer. For this example we are downloading it to the root of the C: drive
```bash
git clone https://github.com/canmet-energy/btap.git
```

## Opening the PAT project and setting up the server
Launch PAT and open the project folder in the btap folder on c:. for example the path would be 
```
C:/btap/pat_projects/necb_national_prototype_scan
```
This should load up the project. 

### Analysis Tab
If you navigate to the Analysis tab (The screwdriver and wrench) you will first see the Analysis type. It is set to "Alogrithmic" and design of experiments (DOE). This algorithm will do a full factorial analysis of the solution space. This means it will run through all the permutations of varibles selected. You can read the backround of the DOE inputs in the R documentation. 

The Default Seed and Default Weather files are set to dummy files. THese files are not used at all. The "Create NECB Prototype Measure" will control the building creation and weather file selection. 

If you scroll down to the "OpenStudio Measures" sections for each measure. You may add your own measures here that you wrote, that are in the BTAP library or on NREL's BCL website.  I will explain the included measures in this project briefly. 
#### Create NECB Measures
This is the measure that will create the archetype building. 

The first variable is the "Building Type". THis will control which building will be created.  The variable is named of type "Discrete" since it is a string and, quite simply it is not a continuous variable. The Static/Default entry is meaningless in this context. The Measure Inputs are the selections you can choose for the run. You can add or remove building types as you need. You cannot have duplicates however.  The Weight is not used for this algorithm either, so you can leave it blank. 

The second items is set to an argument. Is the standard template ruleset to create the model. The template can be set to NECB2011. In the future you will be able to set it to NECB2015 and NECB2017.  You set the field to an argument if the item is NOT to be varied.

The third item is the Climate File. This will choose which climate cities to run the analysis against. ~70 cities have been preselected. If you wish to look at a smaller set, simply remove the cities with the remove button.

#### View Model
This measure will generate the 3D HTML5 Model based on the osm file. 

#### BTAP Utility Tarifs Model Setup
This measure will set up the utility rates for the simulation. It will use the local gas, electricity and oil rates developed by Mike Lubun using the city supplied by the epw file. There are no inputs to this measure. 

#### BTAP Results
This is a special output that collection information from the run into a single JSON file. This is used for data analytic tools like Tableau and the parrallel coordinates visualization.

The first item is a boolean flad to determine if you wish to have hourly results saved to the JSON file. This should be used sparingly as this will create VERY large files.  This is primarily used by CANMETEnergy's communities team to help with district energy system design.

#### OpenStudio Results
This will output the standard, pretty OpenStudio HTML results for every simulation. You can turn on or off the generation of specific section if you wish.  

### Run Tab
Go the the "Run" tab. THis is the tab with the play button on it.  Select "Run on Cloud". This should grant you other options. Click on the "Select a cluster of make a new one"  You should be given two options. Select the 40 cpu option.  This will auto-populate your server setting. 

#### AMI Name
To run the nrcan archetypes the "AMI name" must be set to '2.4.1-nrcan' You will need to set up your Amazon creditials. 
#### Server & Worker Instance Type
You can change the server type. This indicates how much disk space the cpu you are using, and being charged!!!!

#### Number of Workers
This scales the number of workers that you have running as well as the cost!

#### AWS User ID
This identified your cluster instances...helpful if more than one person is running analysis on your Amazon account.  You can sort by this name on the AWS console web interface. 

#### AWS Credentials
Enter your AWS creditials here..See the requirements above for details on how to obtain your access and secret keys.

### Invoking Simulations

#### Start the Cluster

##### Workaround for 2.4.3
NRCan is currently using 2.4.3 server to run the measures.  However, NREL has not added the custom nrcan version to PAT as yet. To workaround this, please use this script to start the server. https://github.com/canmet-energy/start_aws_server You may use the standard way below, but it may not work. 

##### Standard way
To start the cluster, ensure all the fields are completed on the RUN tab and hit the green "Start" button next to "Cluster Status" This may take up to 10 minutes depending on how slow your internet connect is. The Status should turn blue while it is starting.  Once it turns green with a checkmark the cluster should be activated. 

You can inspect the cluster images running on the Amazon website.  Click on the "View AWS Console" and enter your Amazon username and password. Click on the EC2 console and you should see 5 instances running. One server and 4 workers if you picked the 40 cpu. Note this costs a total of $0.56x5 dollars an hour. 

You can inspect the OpenStudio Server by clicking on the bleu  "View Server" button below. You will see the "OpenStudio Cloud Management Console" empty. 

#### Running the Analysis
For starters I would not run the full number of buildings and cities. Choose two of each to start. You can go back to the Analysis tab and reduce the runs if you wish. This should create 4 simulation runs. Then return to the RUN tab and click the "Run Entire Workflow". 

In a minute if you return to the "OpenStudio Cloud Management Console" webpage you will see the job has been submitted and will start queuing the simulations. 

#### Checking for Failures
Go to the "OpenStudio Cloud Management Console" web page and click on View Analysis. It will list simulations that are queued, started and completed. A Status message "Datapoint Failure" would indicate that there was a problem with a simulation run. This can be due to an error in a measure implementation. This is analgous to the PAT interface as well on the RUN tab. 

#### Downloading Results
##### Download a single simulation datapoint
You can download a single datapoint using either the web page or PAT. If your internet connection is sketchy it may fail to download all the datapoints. 

#### Download all simulation result using PAT
You can click on the clouds on the header of the table for the run. One will download all the OSM files and one will download all the Results.  The results will be contained in the folder if C was used as your root. 
```
C:\btap\pat_projects\necb_national_prototype_scan\localResults
```
