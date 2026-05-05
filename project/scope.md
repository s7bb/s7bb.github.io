# Scope of S7BB project

# What
This project should develop an application to check the schedule of the Sbahn S7 in Munich, station Baierbrunn, if it is on time, running late or if trains are canceled. It needs to use the data API from Deutsche Bahn.

# Architecture
This needs to be planned. Ask questions around the architecture. 
Initial idea: On a VM runs a python script accessing the data from the REST API, storing it locally (tbd: where? daily/weekly json files? sqlite?). A website generator should create a website with the data graphically displayed as list and chart (delays, recurrance, ...) (tbd: what is the best method to display this information)
The information should be hosted on github and github pages, where website data (tbd: or the raw data, or both?) needs to be pushed. 


# Tools
python
github
discuss all missing options, especially to create the vizualizations. preffered: typescript

# Target audiance
The audiance are the people living in Baierbrunn, most of them with no no technical background. The information must be presented in a readable and understandable way. 
