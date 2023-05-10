"""
Juan García Sánchez, 2023
"""

###############################################################################
#                                                                             #
# Computer's Files/Folders Explorer: FF Explorer                              #
# Utilities                                                                   #
#                                                                             #
###############################################################################

import os
import glob
import re
import shutil
import zipfile
import gc



'''FF Explorer function'''
def App_Explorer(path, d_type, filter_name = ''):

    d_list = []   # Temporal list to add the files/folders' paths
    d_save = '{}{}'.format('fl' if d_type else 'fd', '-' if filter_name != '' else '')

    if d_type == 0:
        for root, dirs, files in os.walk(path):
            for folder in dirs:
                if filter_name in folder: d_list.append(root + '\\' + folder)
    else:
        for root, dirs, files in os.walk(path):
            for file in files:
                if filter_name in file: d_list.append(root + '\\' + file)

    if len(d_list) != 0:
        a = 1
        with open(path + '\\directory-' + d_save + filter_name + '.txt', 'w') as fp:
            for i in range(len(d_list)):
                try:
                    fp.write(str(d_list[i]) + '\n')
                except:   # If errors raised during saving process, a blank line indicates the missing folder/file in the list
                    fp.write('\n')
    else:
        a = 0

    del d_list   # Delete temporal list to save memory
    gc.collect()

    return a
