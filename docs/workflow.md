# BTAP Development Workflow
This document contains the workflow on how to work with BTAP Measures and the BTAP Standards Projects. 

## Requirements
* [BTAP Development Environment](https://github.com/canmet-energy/btap-development-environment) version 2.6.0
* Github personal or organizational account. 
* CircleCI account (Optional)

# BTAP Measures Workflow
This section details how to use github and develop measure within the BTAP workflow. A prerequisite is reading and understanding the [Measure Writing Guide](http://nrel.github.io/OpenStudio-user-documentation/reference/measure_writing_guide/)
## 0. Create a Work Issue Ticket<a name="create_a_work_issue_ticket"></a>
Lots of people are working on BTAP. By creating a ticket, you are letting people know what you are working on and what progress you are making. If you do not create a ticket, you will work in isolation and you may be duplicating someone else's work that you do not have to do.  Go here and search the issues to see if work is already being done by someone and message them to see if you can help. Otherwise 

1. Create a new issue ticket by clicking 'create new issue'. 
2. Decribe the issue, and give samples of the error you wish to fix  or the feature that you are adding. Please upload neccesary information to reproduce the error including weather or osm files. 
3. Describe your approach and how you are going to test it. 

**Take note of the issue number that is generated from the website. You will need this later. **

 
## 1. Fork Repository
1. Make sure you are logged into GitHub with your account.
2. Go to the [BTAP Measures]( https://github.com/canmet-energy/btap) 
3. Click the Fork button on the upper right-hand side of the repositors page.

Thats it. You now have a copy of the original repository in your GitHub account 

## 2. Making a Local Clone 
Assuming that your username is john_doe you can now clone your repository to your computer by issuing this command in a BTAP-DE terminal terminator. 
```
git clone https://github.com/john_doe/btap.git
```
This will download your repository to your computer. If you were in the /home/osdev folder, you will notice that a new folder called 'btap' was created. Go into that folder by typing:


## 3. Adding a Remote
You will need to tell your github repository where it came from. This is called adding a remote and this will make getting updates from other developers who work off NRCan's repository easier.  To add a remote for the BTAP Measures project. You will first want to be in the btap cloned folder. if you are not already and type: 
```
git remote add upstream https://github.com/canmet-energy/btap.git
```

## 4. Create a Feature Branch
You now need to create a feature branch that you will do your work in. You will want to name the branch using the issue number we created in [Create a Work Issue Ticket](#create_a_work_issue_ticket). For example if your issue number was '123' your branch name should be nrcan_123. To create this branch, you would issue the command while you are in hte btap folder. 
```
git checkout -b nrcan_123
git push origin nrcan_123
``` 
If you go to your repository page on github
At this point you will want to go to your btap_task issue and add a comment that you have created a branch to work on 

## 5. Installing dependencies
Each ruby project manages the use of third party software library dependancies called gems through through a tool called bunlder. This will always execute your measures while in development using these gems. You can control which version or branch of openstudio-standards is used by altering the GEMFILE in the project root folder. Everytime you create a fresh clone, you must perform issue the command to install the gem into your project folder. 
```
bundle install --path vendor/bundle
```
If you make changes to the gem file, or swtich branches, it is a good idea to then issue a update command. 
```
bundle update
```

## 6. <a name="running_all_tests"></a>Running All Tests
It is a very good idea to run the tests locally on your machine before your start working. This is to ensure your starting point is free of errors.  To run the tests you have to run a rake command using bundle. To run the same tests that are part of the automated process that NRCan uses, issue the following command. 
```
bundle exec rake test:measure-tests 
```
This will run with 66% of the available cores that you had made available to your docker container BTAP-DE. 

## 7. Adding a New Measure
NRCan has created a template to make starting a measure a bit easier. It takes care of a bit of the boring argument testing and allows you to focus on what you want to do, write a measure.
Copy the template measure to a new folder in development and follow the instructions on how to modify the measure to your needs.
```bash
cp -R measures_development/btap_template_model_measure measures_development/btap_<your_measure_name>*
```


You can follow the instruction in the template to start your measure development by reading measure.rb and test/test.rb

## 8. <a name="running_your_measure_test">Running your Measure Test. 
To run your test, you will need to use bundler to run the file. To do this type this command in a terminal while in the root BTAP folder.
```coffeescript
bundle exec ruby measures_development/btap_template_<your_measure_name>/test/test.rb
```
Ideally you will be using this or something like this for development. You will need to modify the test to ensure
1. The test exercises a majority of the possible scenarios that your measure will encounter. 
2. Test that the output is correct by testing the result against a stored value. For example if you write a measure that changes the conductances of a wall, ensure that part of the automated test is a comparison of the new wall u-value to what you expected.

Also, to add your test to the list of tests run by step six add the path to the test.rb file to this this file in the BTAP root folder
```
circleci_tests.txt
```

## 9. Pushing your Files to GitHUB
As you develop you will modify, add and sometimes delete files. You will want to save your work in chunks often, even if it is not ready. This can save you time if you take snapshots of your code during development. To do this you must determine the STATUS of your local changes,  ADD your changes, and COMMIT your changes locally and then PUSH your changes to the server. I personally do this daily, but it could be more frequent than that. So at the end of everyt day I do a Status, add, commit and push. 

### Get STATUS
You will need to know what changes you have made to the files. You can use the command status to list all the files that you changed. 
```
git status
```

* **Untracked Files**: Files that are not currently under GIT management. 
* **Changes not staged for commit**: These are files that are under git management but changes have not been staged into a commit. 

### ADDing files to be commited
This command will add files to be staged for commiting. This tells git to group the files you wish to group into a commit. So to add the changes you made to an existing file, to add a new file, or a new folder into the next commit, you issue the command. 
```bash
git add path_to_your_file_or_folder
```
You can use issue the status command again to see what you have added. 

### COMMITing Files
Now you want to name your commit. This bundles all the changes you have made into something that is names and the you can revert to if you screw up your work and you are not sure how you broke things. You can do this by issueing the git commit command: 
```bash
git commit -m'tell a story of what you have just changed' 
```
The '-m' switch allows you to give a description of what you have accomplished. 

### RESET to your last commit
As I mentioned above.. sometime you just want to undo what you did up to your last commit. This happens when you have made so many changes that really did not make sense and you want to get back to your last version. An easy way to do that is using the reset command the following way. Warning: This will delete files and revert all the changes back to your last commit. 
```bash
git reset --hard HEAD
```

### PUSH your changes Online
If you want others to see your work, comment on your code, and generally save your hard work to a secure backed up resource, you need to PUSH your work to your server. This is very easily done by issuing the push command. 
```bash
git push origin nrcan_123
```
It will ask for your username and password. and it should push your changes to your personal repository.  If you go to your git clone https://github.com/john_doe/btap.git repository you should see your branch commit listed as the most recent commit. **NEVER PUSH TO MASTER BRANCH ANYWHERE**

## <a name="syncing"> 10. Keeping Your Fork in Sync (Merging) 
By the way, your forked repository doesnt automatically stay in sync with the original repository; you need to take care of this yourself. After all, in a healthy open source project, multiple contributors are forking the repository, cloning it, creating feature branches, committing changes, and submitting pull requests. I do this daily. 

To keep your fork in sync with the original repository, use these commands:
```bash
# Switch to master branch
git checkout master && git pull upstream master && git push origin master
# Your master is now up to date with NRCan's master. 
# Checkout your working Branch. 
git checkout nrcan_123
# Merge your master with your current branch nrcan_123
git merge origin master
# Deal with any conflicts then push to your server repository. 
```
You will then need to deal with any conflicts.  Conflicts are when you and someone else have modified the same file. It is your job to reconcile the differences. So you need to look at their changes and your changes and ensure the code is reconciled to satisfy both needs. You can list the conflicted files by issuing a 'git status' command. In these files you will notice a series of '========' to denote their code and your code changes. This may require you to talk to the other author to understand what she was doing. 

Once this is done, you need to ADD the files using the 'git add' command. and then commit and push as above.
Note: While it is tempting to use rebase in this situation, and resolve the conflicts in a serial manner, if you do anything wrong or cancel the process the local repository could be left in an unfinished state and may corrupt the history. 



## 11. Submitting a Pull request to NRCan
* Ensure that your fork branch is [synced](#synced) with NRCan master branch. 
* Your tests have been [added or modified as needed](#running_your_measure_test)
* Ensure to [run all the tests](#running_all_tests) and that they all pass locally.
* Go to your repository website
* Select your branch that you are working on. 
* Click 'Create Pull Request'
* Select the pull branches and forks as following
```
base fork:canmet-energy/btap - base:master <- head fork:<your_git_account_name>/btap - compare:<nrcan_123>
```
This should tell you if you can merge.
* Assign a reviewer. This should be someone from NRCan, and your local supervisor if you have one. 
* Send a message to your reviewer(s) via email or some other means with a link to the pull request url 
* The review may ask for a code review to be scheduled if there are questions to be answered. 
* Reviewer will commit the code and close the pull request. 

### NRCan Staff


#Clone your repository (Script) 
```
# After you have forked the btap repository to your account using the webpage modify the BRANCH_NAME and GIT_ACCOUNT to your
# 
export BRANCH_NAME=nrcan_123 && \
export GIT_ACCOUNT=phylroy && \
git clone https://github.com/$GIT_ACCOUNT/btap.git && \
cd btap && \
git remote add upstream https://github.com/canmet-energy/btap.git && \
bundle install --path vendor/bundle && \
git checkout -b nrcan_$BRANCH_NAME && \
git push origin nrcan_$BRANCH_NAME && \
bundle install --path vendor/bundle && \
bundle exec rake test:measure-tests
```
#Update Your branch(Script)
```
export BRANCH_NAME=nrcan_123 && \
git checkout master && \
git pull upstream master && \ 
git push origin master && \
git checkout nrcan_123 && \
git merge origin master
``` 

