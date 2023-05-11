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
import shutil
import zipfile
import gc



'''FF Explorer function'''
def App_Explorer(path, d_type, action, filter_name = ''):

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
        if action == 1:
            with open(path + '\\directory-' + d_save + filter_name + '.txt', 'w') as fp:
                for i in range(len(d_list)):
                    try:
                        fp.write(str(d_list[i]) + '\n')
                    except:   # If errors raised during saving process, a blank line indicates the missing folder/file in the list
                        fp.write('\n')
        else:
            if action == 3:   # Before being deleted, files/folders can be compressed in a .zip directly in the source path
                if d_type:   # Compressing files in a single .zip folder
                    with zipfile.ZipFile(path + '/Compressed_data.zip', 'w', zipfile.ZIP_DEFLATED, allowZip64 = True) as zf:
                        for fl in d_list:
                            zf.write(fl, fl.split('\\')[-1])
                else:   # Compressing folders separately
                    for fd in d_list:
                        with zipfile.ZipFile(path + fd.split('\\')[-1] + '.zip', 'w', zipfile.ZIP_DEFLATED, allowZip64 = True) as zf:
                            for fl in os.listdir(fd):
                                zf.write(fd + '\\' + fl, fl)
            if d_type:
                for fl in d_list:
                    os.remove(fl)
            else:
                for fd in d_list:
                    shutil.rmtree(fd, ignore_errors = False, onerror = None)
    else:
        a = 0

    del d_list   # Delete temporal list to save memory
    gc.collect()

    return a
