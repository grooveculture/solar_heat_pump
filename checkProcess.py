from subprocess import check_output
p = check_output(['node', 'fetchTOventrop.js'])
print (p)