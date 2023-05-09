"""
Juan García Sánchez, 2023
"""

###############################################################################
#                                                                             #
# Computer's Files/Folders Explorer: FF Explorer                              #
#                                                                             #
###############################################################################

from tkinter import *
from tkinter import ttk, font, messagebox, filedialog, PhotoImage
# from PIL import ImageTk, Image
import os
import gc



# ================= Program parameters ==========

__author__ = 'Juan García Sánchez'
__title__= 'FF Explorer'
__rootf__ = os.getcwd()
__version__ = '1.0'
__datver__ = '05-2023'
__pyver__ = '3.10.9'
__license__ = 'GPLv3'



# ================= UI class ====================

class FFE_UI(Tk):

    def __init__(self):

# Main properties of the UI
        Tk.__init__(self)
        self.title(__title__)
        self.geometry('235x360+800+350')
        self.resizable(False, False)
        self.lift()
        self.focus_force()
        # titlebar_icon = PhotoImage(__rootf__ + "/Python.ico")
        # taskbar_icon = PhotoImage(__rootf__ + "/Python.ico")
        self.iconbitmap(default = __rootf__ + "/Python.ico")
        # self.iconphoto(False, titlebar_icon)
        self.config(bg = "#bfbfbf")

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
        self.source = StringVar(value = '*Select or drag path here*')   # Source path variable
        self.seed = StringVar(value = '')   # Files/folders' name filter, string that is contained in files/folders' name
        self.d_type = IntVar(value = 0)   # 0, folder directory; 1, file directory
        self.list_options = ['*Select action*','Save list','Remove list','Compress list']   # List with options to handle the directory obtained

# UI layout

        lab_path = Label(self, text = "Source path", bd = 2, bg = "#999999", **self.font_title1, justify = CENTER, width = 18)
        lab_path.grid(row = 0, column = 0, padx = 10, pady = 7, ipadx = 10, ipady = 5)
        self.ent_path = Entry(self, textvariable = self.source, bd = 5, bg = "white", fg = "black", font = "Verdana 11", justify = LEFT, relief = SUNKEN, state = "readonly", cursor = "hand2", width = 18)
        self.ent_path.grid(row = 1, column = 0, padx = 10, pady = 5, ipadx = 10, ipady = 5)
        self.ent_path.bind("<1>", self.source_selection)
        self.ent_path.bind("<MouseWheel>", lambda event: self.ent_path.xview_scroll(int(event.delta/40), 'units'))

        lab_filter = Label(self, text = "Name seed", bd = 2, bg = "#999999", **self.font_title1, justify = CENTER, width = 18)
        lab_filter.grid(row = 2, column = 0, padx = 10, pady = 7, ipadx = 10, ipady = 5)
        ent_filter = Entry(self, textvariable = self.seed, bd = 5, bg = "white", fg = "black", font = "Verdana 11", justify = LEFT, relief = SUNKEN, width = 18)
        ent_filter.grid(row = 3, column = 0, padx = 10, pady = 5, ipadx = 10, ipady = 5)
        ent_filter.bind("<MouseWheel>", lambda event: ent_filter.xview_scroll(int(event.delta/40), 'units'))

        Rd_opt1 = Radiobutton(self, text = "Folders", var = self.d_type, value = 0, bd = 2, activebackground = "#bfbfbf", activeforeground = "green", bg = "#bfbfbf", fg = "black", font = "Verdana 11", justify = LEFT)
        Rd_opt1.grid(row = 4, column = 0, padx = 15, pady = 7, ipadx = 1, ipady = 5, sticky = W)
        Rd_opt2 = Radiobutton(self, text = "Files", var = self.d_type, value = 1, bd = 2, activebackground = "#bfbfbf", activeforeground = "green", bg = "#bfbfbf", fg = "black", font = "Verdana 11", justify = LEFT)
        Rd_opt2.grid(row = 4, column = 0, padx = 15, pady = 7, ipadx = 1, ipady = 5, sticky = E)
        self.Cb_opt3 = ttk.Combobox(self, values = self.list_options, background = "#e6e6e6", state = "readonly", width = 18)
        self.Cb_opt3.set(self.list_options[0])
        self.Cb_opt3.grid(row = 5, column = 0, padx = 10, pady = 5, ipadx = 10, ipady = 5)

        but_accept = Button(self, text = "Run", relief = RAISED, command = self.accept, **self.style_but, **self.font_but, width = 5)
        but_accept.grid(row = 6, column = 0, padx = 10, pady = 10, ipadx = 10, ipady = 5)

# UI contextual menu
        self.menucontext = Menu(self, tearoff = 0)
        self.menucontext.add_command(label = "About...", command = lambda : print('Author: ' + __author__ + '\nLicense: ' + __license__))
        self.menucontext.add_command(label = "Exit", command = self.exit)

        self.bind("<3>", self.show_menucontext)

# UI mainloop
        self.mainloop()



# Additional functions of the class
    def source_selection(self, event):
        adress = filedialog.askdirectory(initialdir = "", title = "FF Explorer, source path selection")
        if adress != '':
            self.source.set(adress)
            self.ent_path.xview_moveto(1)


    ''' Show contextual menu'''
    def show_menucontext(self, e):
        self.menucontext.post(e.x_root, e.y_root)


    def accept(self):
        if self.source.get() == '*Select or drag path here*':
            messagebox.showwarning("Warning!", "Source path not added")
        elif self.Cb_opt3.get() == '*Select action*':
            messagebox.showwarning("Warning!", "No action selected")
        else:
            print("done")


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