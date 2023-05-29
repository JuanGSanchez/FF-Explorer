"""
Juan García Sánchez, 2023
"""

###############################################################################
#                                                                             #
# Computer's Files/Folders Explorer: FF Explorer                              #
# UI                                                                          #
#                                                                             #
###############################################################################

from tkinter import *
from tkinter import ttk, font, messagebox, filedialog, PhotoImage
import os
import gc

from FF_utils import App_Explorer



# ================= Program parameters ==========

__author__ = 'Juan García Sánchez'
__title__= 'FF Explorer'
__rootf__ = os.getcwd()
__version__ = '1.0'
__datver__ = '05-2023'
__pyver__ = '3.11.3'
__license__ = 'GPLv3'



# ================= UI class ====================

class FFE_UI(Tk):

    def __init__(self):

# Main properties of the UI
        Tk.__init__(self)
        self.title(__title__)
        width = 235
        height = 360
        x_pos = (self.winfo_screenwidth() - width - self.winfo_rootx() + self.winfo_x())//2
        y_pos = (self.winfo_screenheight() - height - self.winfo_rooty() + self.winfo_y())//2
        self.geometry('{}x{}+{}+{}'.format(width, height, x_pos, y_pos))
        self.resizable(False, False)
        self.lift()
        self.focus_force()
        icon = PhotoImage(file =  __rootf__ + "/Logo FFE.png")
        self.iconphoto(False, icon)
        self.config(bg = "#bfbfbf")

# Style settings
        default_font = font.nametofont("TkDefaultFont")
        default_font.configure(family = 'TimesNewRoman', size = 12)
        self.option_add("*Font", default_font)  # Default font      

        style_but = {'bg' : "white", 'fg' : 'black', 'font' : "Arial 12", 'activebackground' : 'white', 'activeforeground' : 'black'}
        style_opts = {'bg' : '#bfbfbf', 'fg' : 'black', 'font' : 'Verdana 12', 'activebackground' : '#bfbfbf', 'activeforeground' : 'green'}
        font_title = {'bg' : '#999999', 'fg' : 'blue', 'font' : 'Arial 12 bold'}
        font_entry = {'bg' : 'white', 'fg' : 'black', 'font' : 'Verdana 11'}
        font_man = {'bg' : 'darkblue', 'font' : "Arial 11", 'fg' : 'white'}

# UI variables
        self.source = StringVar(value = '*Select path here*')   # Root path variable
        self.seed = StringVar(value = '')   # Files/folders' name filter, string that is contained in files/folders' name
        self.d_type = IntVar(value = 0)   # 0, folder directory; 1, file directory
        self.dict_options = {'*Select action*': -1, 'Save list': 1, 'Remove list': 2, 'Compress list': 3}   # List with options to handle the directory obtained

# UI layout
        ''' Source path selection, from which all nested files or folders will be listed '''
        lab_path = Label(self, text = "Root path", justify = CENTER, bd = 2, width = 18, **font_title)
        lab_path.grid(row = 0, column = 0, padx = 10, pady = 7, ipadx = 10, ipady = 5)
        self.ent_path = Entry(self, textvariable = self.source, justify = LEFT, bd = 5, relief = SUNKEN, state = "readonly", cursor = "hand2", width = 18, **font_entry)
        self.ent_path.grid(row = 1, column = 0, padx = 10, pady = 5, ipadx = 10, ipady = 5)
        self.ent_path.bind("<1>", self.source_selection)
        self.ent_path.bind("<MouseWheel>", lambda event: self.ent_path.xview_scroll(int(event.delta/40), 'units'))

        ''' Stablishment of a name seed, a chain of characters that must be included in the file/folder name.
        It acts as a filter tool; by leaving it blank, all nested files/folders will be listed '''
        lab_filter = Label(self, text = "Name seed", justify = CENTER, bd = 2, width = 18, **font_title)
        lab_filter.grid(row = 2, column = 0, padx = 10, pady = 7, ipadx = 10, ipady = 5)
        ent_filter = Entry(self, textvariable = self.seed, justify = LEFT, bd = 5, relief = SUNKEN, width = 18, **font_entry)
        ent_filter.grid(row = 3, column = 0, padx = 10, pady = 5, ipadx = 10, ipady = 5)
        ent_filter.bind("<MouseWheel>", lambda event: ent_filter.xview_scroll(int(event.delta/40), 'units'))

        ''' Selection block, type of files and action to be performed '''
        Rd_opt1 = Radiobutton(self, text = "Folders", var = self.d_type, value = 0, justify = LEFT, bd = 2, **style_opts)
        Rd_opt1.grid(row = 4, column = 0, padx = 15, pady = 7, ipadx = 1, ipady = 5, sticky = W)
        Rd_opt2 = Radiobutton(self, text = "Files", var = self.d_type, value = 1, justify = LEFT, bd = 2, **style_opts)
        Rd_opt2.grid(row = 4, column = 0, padx = 15, pady = 7, ipadx = 1, ipady = 5, sticky = E)
        self.Cb_opt3 = ttk.Combobox(self, values = list(self.dict_options.keys()), background = "#e6e6e6", state = "readonly", width = 18)
        self.Cb_opt3.set(list(self.dict_options.keys())[0])
        self.Cb_opt3.grid(row = 5, column = 0, padx = 10, pady = 5, ipadx = 10, ipady = 5)

        ''' Run button '''
        but_run = Button(self, text = "Run", bd = 3, relief = RAISED, command = self.accept, **style_but, width = 5)
        but_run.grid(row = 6, column = 0, padx = 10, pady = 10, ipadx = 10, ipady = 5)

# UI manual
        text_man1 = 'Root path in which\nfiles or folders are searched.'
        text_man2 = "List of consecutive characters\ncontained in files/folders' name."
        text_man3 = 'Folders search.'
        text_man4 = 'Files search.'
        text_man5 = 'Actions to be applied to\nthe resulting directory.'
        self.aux_man = ['', '\n   Save directory of files/folders found', '\n   Delete files/folders found',
                        '\n   For files, compress all in one .zip in root\n   For folders, compress each one in root', '']
        fr_man = Toplevel(self, bd= 2, bg = 'darkblue')
        fr_man.resizable(False, False)
        fr_man.overrideredirect(True)
        fr_man.wm_attributes('-alpha', 0.8)
        fr_man.withdraw()
        self.fr_lab = Label(fr_man, justify = LEFT, bd = 2, **font_man)
        self.fr_lab.grid(padx = 1, pady = 1, sticky = W)
        self.ent_path.bind("<Motion>", lambda event : self.show_manual(event, fr_man, [211, 39, 200, 45], text_man1))
        ent_filter.bind("<Motion>", lambda event : self.show_manual(event, fr_man, [211, 39, 220, 45], text_man2))
        Rd_opt1.bind("<Motion>", lambda event : self.show_manual(event, fr_man, [90, 30, 115, 30], text_man3))
        Rd_opt2.bind("<Motion>", lambda event : self.show_manual(event, fr_man, [70, 30, 100, 30], text_man4))
        self.Cb_opt3.bind("<Motion>", lambda event : self.show_manual(event, fr_man, [200, 30, 165, 45], text_man5))
        self.Cb_opt3.bind("<<ComboboxSelected>>", lambda event : self.show_manual_action(fr_man, [70, 30, 165, 45], text_man5))

# UI contextual menu
        self.menucontext = Menu(self, tearoff = 0)
        self.menucontext.add_command(label = "About...", command = lambda : print('Author: '
                                    + __author__ + '\nVersion: ' + __version__ + '\nLicense: ' + __license__))
        self.menucontext.add_command(label = "Exit", command = self.exit)

# UI bindings
        self.bind("<3>", self.show_menucontext)
        self.bind("<Return>", lambda event: self.accept())
        self.bind("<Control_R>", lambda event: self.exit())

# UI mainloop
        self.mainloop()


# Additional functions of the class
    ''' Source directory selection function '''
    def source_selection(self, event):
        adress = filedialog.askdirectory(initialdir = "", title = "FF Explorer, root path selection")
        if adress != '':
            self.source.set(adress)
            self.ent_path.xview_moveto(1)


    ''' Show auxiliar manual widget '''
    def show_manual_action(self, fr, pos, text_man):
        self.fr_lab.config(text = text_man + self.aux_man[self.dict_options[self.Cb_opt3.get()]])
        match self.dict_options[self.Cb_opt3.get()]:
            case -1:
                pass
            case 0:
                pass
            case 1:
                pos[2], pos[3] = 250, 63
            case 2:
                pos[2], pos[3] = 185, 63
            case 3:
                pos[2], pos[3] = 285, 78
        fr.geometry('{}x{}+{}+{}'.format(pos[2], pos[3], self.winfo_pointerx() + 20, self.winfo_pointery() + 20))


    ''' Show manual widget '''
    def show_manual(self, e, fr, pos, text_man):
        if 0 < e.x < pos[0] and 0 < e.y < pos[1]:
            fr.deiconify()
            if str(e.widget) == '.!combobox':
                self.fr_lab.config(text = text_man + self.aux_man[self.dict_options[self.Cb_opt3.get()]])
                match self.dict_options[self.Cb_opt3.get()]:
                    case -1:
                        pass
                    case 0:
                        pass
                    case 1:
                        pos[2], pos[3] = 250, 63
                    case 2:
                        pos[2], pos[3] = 185, 63
                    case 3:
                        pos[2], pos[3] = 285, 78
            else:
                self.fr_lab.config(text = text_man)
            fr.geometry('{}x{}+{}+{}'.format(pos[2], pos[3], e.x_root + 20, e.y_root + 20))
        else:
            fr.withdraw()


    ''' Show contextual menu '''
    def show_menucontext(self, e):
        self.menucontext.post(e.x_root, e.y_root)


    ''' Run function '''
    def accept(self):
        if self.source.get() == '*Select path here*':   # Check if path is introduced
            messagebox.showwarning("Warning!", "Source path not added")
        elif self.Cb_opt3.get() == '*Select action*':   # Check if action is selected
            messagebox.showwarning("Warning!", "No action selected")
        else:   # Execute application function
            token = App_Explorer(self.source.get(), self.d_type.get(), self.dict_options[self.Cb_opt3.get()], self.seed.get())
            ending = 'saved' if self.dict_options[self.Cb_opt3.get()] == 1 else 'deleted' if self.dict_options[self.Cb_opt3.get()] == 2 else 'compressed'
            if token:
                print('  Directory {}.'.format(ending))
            else:
                print('  No {} was found, nothing was {}.'.format('file' if self.d_type.get() else 'folder', ending))


    ''' Exit function '''
    def exit(self):
        print('Exiting FF Explorer...')
        self.quit()
        self.destroy()
        for name in dir():
            if not name.startswith('_'):
                del locals()[name]
        gc.collect()
        del self



# ================= UI execution ================

if __name__ == '__main__':
    FFE_UI()