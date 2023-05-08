"""
Juan García Sánchez, 2023
"""

###############################################################################
#                                                                             #
# Computer's Files/Folders Explorer: FF Explorer                              #
#                                                                             #
###############################################################################

from tkinter import *
from tkinter import ttk, font, messagebox, filedialog, scrolledtext
from PIL import ImageTk, Image
import os



# ================= Program parameters ==========

__author__ = 'Juan García Sánchez'
__title__= 'FFExplorer'
__rootf__ = os.getcwd()
__version__ = '1.0'
__datver__ = '05-2023'
__pyver__ = '3.10.9'
__license__ = 'GPLv3'



class FFE_UI(Tk):
    def __init__(self):

# Main properties of the UI
        Tk.__init__(self)
        self.title(__title__)
        self.geometry('250x400+800+350')
        self.resizable(False, False)
        self.lift()
        self.focus_force()
        self.iconbitmap(default = __rootf__ + "/Python.ico")

# Style settings
        default_font = font.nametofont("TkDefaultFont")
        default_font.configure(family = 'TimesNewRoman', size = 11)
        self.option_add("*Font", default_font)  # Fuente predeterminada        
        fuente_menu = font.Font(font = "Arial 12 bold")
        font_submenu = {'font' : "Arial 11", 'fg' : 'black'}
        fuente_aux1 = font.Font(font = "Helvetica 11 italic")
        fuente_aux2 = font.Font(font = "TimesNewRoman 11")
        fuente_aux3 = font.Font(font = "Verdana 12 roman")
        fuente_aux4 = font.Font(font = "Arial 12 bold")

        self.style_but = {'bd' : '3', 'bg' : "white", 'activebackground' : 'white', 'activeforeground' : 'black'}
        self.font_title1 = {'font' : "Arial 12 bold", 'fg' : 'blue'}
        self.font_title2 = {'font' : "Arial 14 bold", 'fg' : 'blue'}
        self.font_title3 = {'font' : "Arial 12 bold", 'fg' : 'black'}
        self.font_but = {'font' : "Arial 12", 'fg' : 'black'}
        self.font_text = {'font' : "Arial 11", 'fg' : 'black'}

# UI variables
        self.source = StringVar(value = '')
        self.seed = StringVar(value = '')
        self.d_type = IntVar(value = 0)
        self.list_options = ['Select action','Save list','Remove list','Compress list']

# UI layout

        lab_path = Label(self, text = "Source path", bd = 2, bg = "#999999", **self.font_title1, justify = CENTER)
        lab_path.grid(row = 0, column = 0, padx = 5, pady = 5, ipadx = 10, ipady = 5, sticky = W+E)
        self.ent_path = Entry(self, textvariable = self.source, bd = 5, bg = "white", fg = "black", font = "Verdana 11", justify = LEFT, relief = SUNKEN, state = "readonly", cursor = "cross")
        self.ent_path.grid(row = 1, column = 0, padx = 5, pady = 5, ipadx = 10, ipady = 5, sticky = W+E)
        self.ent_path.bind("<1>", self.source_selection)

        lab_filter = Label(self, text = "Name seed", bd = 2, bg = "#999999", **self.font_title1, justify = LEFT)
        lab_filter.grid(row = 2, column = 0, padx = 5, pady = 5, ipadx = 10, ipady = 5, sticky = W+E)
        ent_filter = Entry(self, textvariable = self.seed, bd = 5, bg = "white", fg = "black", font = "Verdana 11", justify = LEFT, relief = SUNKEN)
        ent_filter.grid(row = 3, column = 0, padx = 5, pady = 5, ipadx = 10, ipady = 5, sticky = W+E)
        Rd_opt1 = Radiobutton(self, text = "Folders", var = self.d_type, value = 0, bd = 2, activebackground = "#bfbfbf", activeforeground = "green", bg = "#bfbfbf", fg = "black", font = "Verdana 11", justify = LEFT)
        Rd_opt1.grid(row = 4, column = 0, padx = 5, pady = 5, ipadx = 10, ipady = 5, sticky = W)
        Rd_opt2 = Radiobutton(self, text = "Files", var = self.d_type, value = 1, bd = 2, activebackground = "#bfbfbf", activeforeground = "green", bg = "#bfbfbf", fg = "black", font = "Verdana 11", justify = LEFT)
        Rd_opt2.grid(row = 4, column = 0, padx = 5, pady = 5, ipadx = 10, ipady = 5, sticky = E)

        but_accept = Button(self, text = "Run", relief = RAISED, command = self.accept, **self.style_but, **self.font_but, width = 7)
        but_accept.grid(row = 3, column = 0, padx = 5, pady = 5, ipadx = 10, ipady = 5, sticky = E)

# UI mainloop
        self.mainloop()



# Additional functions of the class

    def source_selection(event, self):
        adress = filedialog.askdirectory(initialdir = "CFO_main", title = "Accesories, main folder selection")
        if adress != '':
            self.name_folder1.set(adress)
            self.ent_folder1.xview_moveto(1)


    def accept(self):
        if self.name_folder1.get() == '':
            messagebox.showwarning("Warning!", "Folders entries not completed:\n\n         Main folder")
        else:
            print("done")


# ================= UI execution ================

if __name__ == '__main__':
    FFE_UI()