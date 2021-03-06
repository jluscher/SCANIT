#! /usr/bin/python
#
# SCANIT - Control A spectrometer and collect data
#
# LICENSE:
# This work is licensed under the Creative Commons Zero License
# Creative Commons CC0. 
# To view a copy of this license, visit
# http://directory.fsf.org/wiki/License:CC0
# or send a letter to:
# Creative Commons, PO Box 1866, Mountain View, CA 94042, USA.
#
# Author: James Luscher, jluscher@gmail.com
#
import sys, string, time
import serial
#
from pathlib import Path
#
from tkinter import *
from tkinter import font
from tkinter import filedialog
from tkinter.ttk import Progressbar
# from tkinter import ttk
# from tkinter.scrolledtext import *

import tkinter.messagebox as mBox
# import tkinter.simpledialog as simpledialog

import matplotlib
from matplotlib.widgets import Cursor
matplotlib.use('TkAgg')
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

import numpy 
from numpy import searchsorted


siTitle = 'SCANIT for RetroSPEX [v036]'   # Program name and version
TANBG = '#F8E2CD'           # Background color
WARNC = '#FFBBFF'           # Warning color (pinkish)
ACTIVB = '#F07748'          # activebackground color for buttons    
#
jjltest = True      # print messages, testing
comtest = False     # print communication diagnostic details (much!)
crqtest = False     # print command/response queue details
pausetest = True    # print unsolicited button actions

## code based on example from:  http://robotic-controls.com/learn/python-guis/tkinter-serial
#  modified for Python3
#
#  Serial() argument added:  rtscts=1
#
## NOTE:  PATCH @  http://sourceforge.net/p/pyserial/patches/37/
#  /usr/local/lib/python3.4/dist-packages/serial/serialposix.py
# at (about) line # 480:
#             except select.error as e:
#                 # ignore EAGAIN errors. all other errors are shown
#           *     # see also http://www.python.org/dev/peps/pep-3151/#select
#           *     # patch: James Luscher (re:
#           *     # http://sourceforge.net/p/pyserial/patches/37/ )
#           *     #if e[0] != errno.EAGAIN:
#           *     if e.errno != errno.EAGAIN:
#                     raise SerialException('read failed: %s' % (e,))
#

# communication commands
COMmands = '''
Command     => Response Command sent => Response received
----------------------- LOW LEVEL -- FPGA --------------
?           => <Help text>   Help (display SPEX commands)
c           => <header>      Clear Screen
i           => i             Warm Initialize
f           => f             Reset FPGA
r AA        => r AA DD       Read DD from address AA (hex)
w AA DD     => w AA DD       Write data DD to address AA (or V/V??)
s           => s AA DD       Show AdrREG and DataReg  (AA DD ??)
p           => p FF          Report PMT Control Register setting
b           => B n           Report Button State, 0/1  (Off/On)
v n         => v n           Verbose n=0/1 (Off/On)
----------------------- HIGH LEVEL -- SPECTROMETER -----
L n         => L n           Set LED n=0/1 (Off/On)
D n FFFF    => D n FFFF      Load DAC #n with FFFF (hex)
A n         => A n FFFF      Report High Voltage on #n
E n         => E n           Enable PMT counter #n (0~7), Clears count
T 7FFFFFFF  => T 7FFFFFFF    Set Integration time, milliseconds
>           => Wait For Bang Start Measurement ('!' signals Done)
P n         => P n FFFEFFFEFFFF  Dump PMT counter #n (0~2)
X s7FFFFFFF => X s7FFFFFFF   Move eXcitation, s=+/- (direction), 7FFFFFFF (steps)
M s7FFFFFFF => M s7FFFFFFF   Move eMission, s=+/- (direction), 7FFFFFFF (steps)
----------------------- CONTROLLER INITIATED ALERTS ----
            => ! FF          Limit reached [bits?] Motion (done?) time (done?)
            => # n           Button activity (reports state?  0/1  (Off/On))
'''
COMchr0 = list('?cifrwspbvLDAET>PXM')
RSPalert = ['!','#']
RSPnorm  = ['?','r','s','p','B','A','P']

#make our own buffers
serialPort = None           # we always start before any port is found
portName   = 'OFFLINE'      # ... and any connection established
serOutReady = False         # RetroSPEX has been Initialized
crQbusy     = False         # RetroSPEX is executing a command (busy)
crQcmd      = ''            # ... command being executed
crQrsp      = ''            # ... response being awaited
crQnxt      = None          # ... function to execute upon response.
#
serInBuffer = ""            # 'string' type (character input storage)
serOutBuffer = "".encode()  # 'byte' type
serInLines   = []           # list of complete input lines


#=====================================================================
## SCANIT Window  (GUI window for Spectrometer Control & Data Capture)
#
siWinW = 1260    # width
siWinH = 760     # height
#
siWin = Tk()
siWin.title(siTitle)
siWin['bg'] = TANBG   # background color
if jjltest:
    siWin.geometry('+670+50')   # shift to right for testing
    transGeom = '+780+250'       # ... for 'transient' screens
else:
    siWin.geometry('{}x{}+0+0'.format(siWinW,siWinH))
    transGeom = '+110+200'      # ... for 'transient' screens
#siWin.geometry('{}x{}+80+50'.format(siWinW,siWinH))
#siWin.geometry('+50+50')    # window in upper-left of screen

#
monoFont10 = font.Font(family='Ubuntu Mono', size=10)
monoFont12 = font.Font(family='Ubuntu Mono', size=12)
monoFont14 = font.Font(family='Ubuntu Mono', size=14)
monoFont16 = font.Font(family='Ubuntu Mono', size=16)
monoFont24 = font.Font(family='Ubuntu Mono', size=24)


#=====================================================================
## Global variables  (for Spectrometer Control & Data Capture)
#
#==============
#  Default Acquisition Settings:   
#
# User Default Settings to be used for Measurement
# (settable and saved/restored)
#  recovered from configuration data ('settings.txt')
varEXinc = StringVar()   # Setting EX Inc   Wavelength (nm)
varEMinc = StringVar()   # Setting EM Inc   Wavelength (nm)
varTMinc = StringVar()   # Setting TM Inc   time (s)
#
#==============
#  Site  Established Settings:   
#  recovered from configuration data ('settings.txt')
varEXslit = StringVar()   # Slit size EX (nm)
varEXslit = StringVar()   # Slit size EM (nm)
varEMhv         = StringVar()   # EM PMT high voltage (v)
varREFhv        = StringVar()   # REF PMT high voltage (v)
varREFdiodeG    = StringVar()   # REF DIODE Gain setting [0,1,2,3]
#
#==============
#  Live Data (acquired)
#
varLiveEMhv         = StringVar()   # Live EM PMT high voltage (v)
varLiveREFhv        = StringVar()   # Live REF PMT high voltage (v)
varLiveEXpos        = StringVar()   # Live Excitation position nm
varLiveEMpos        = StringVar()   # Live Excitation position nm
varLiveSignal       = StringVar()   # Live Signal (PMT) reading (counts)
varLiveReference    = StringVar()   # Live Reference (diode/PMT) reading (counts)
#
# Transient states
offLine = True             # No Spectrometer connection made (serial - USB)
#
#==============
#  scan data acquired
#
varScanDataFileName = StringVar()   # File name (path) where Scan Data was saved
varScanDataFileName.set('')         # none initially
#
scanDataX = []      # X value sample was taken at (wavelength / time)
scanDataY = []      # Y value of sample - PMT counts
#
ax = None           # forward referenc for Plot Object (setPlotTitle())
#
#==============
#  background: input data from previous scan (for reference)
#
varRefFileName = StringVar()    # File name (path) for Reference Data in Plot
varRefFileName.set('')          # none initially
#
inputFileHdr  = []  # Header section from fileLoad
inputFileData = []  # Data   section from fileload
#
backgroundDataX = []     # X value sample was taken at (wavelength / time)
backgroundDataY = []     # Y value of sample - PMT counts
#
#==============
#  dayfile:   data about the experiments being done today
#
dayFileData = []  # Data   section from fileload / or for writing
#
varDayDate       = StringVar()  # Date this data was entered
varDayMeaning1   = StringVar()  # Meaning of Experiment
varDayMeaning2   = StringVar()  # Meaning of Experiment
varDayMeaning3   = StringVar()  # Meaning of Experiment
varDayEXslit     = StringVar()  # Excitation slit wavelength nm
varDayEMslit     = StringVar()  # Emission slit  Wavelength nm
varDayBulb       = StringVar()  # Bulb Intensity
varDayNotebook   = StringVar()  # Notebook Page
varDayOther1     = StringVar()  # Other comments
varDayOther2     = StringVar()  # Other comments
varDayOther3     = StringVar()  # Other comments
#
#==============
#  type of scan
EXscan = 0
EMscan = 1
TMscan = 2
scanName = [ 'EX', 'EM', 'TM' ]
varScanMode     = IntVar()     # Determines type of scan taken
#
#==============
#   scanner STATE (operating, paused, stopped)
#   NOTE:  'stopped' blinking (and the others) only while connected !!
STATEstop  = 0
STATEscan  = 1
STATEpause = 2
scannerState = STATEstop     # scanner operating mode
#
# blink speed:  duty-cycle  --  (ms ON, ms OFF)
#              stopped    scanning   paused
blinkSpeed = [(50,2000), (2000,50), (250,250)]
#
# default speed is STATEstop (non-scanning)
blinkOnTime, blinkOffTime  =   blinkSpeed[STATEstop]
#
# pushing the Front Panel Button => toggles "Pause" display for LED (above)
# IF  scannerState == STATEscan and  varScanMode == TMscan  (time)
# ... (or if pauseTest == True) ;-)
# ( see  panelButton(txt)  below ) 


#
# settings used for scanned data waveforms
#
varEXwaveStart  = StringVar()  # Excitation Start Wavelength nm
varEXwaveEnd    = StringVar()  # Excitation End   Wavelength nm
varEXwaveInc    = StringVar()  # Excitation Inc   Wavelength nm
#
varEMwaveStart  = StringVar()  # Emission Start Wavelength nm
varEMwaveEnd    = StringVar()  # Emission End   Wavelength nm
varEMwaveInc    = StringVar()  # Emission Inc   Wavelength nm
#
varTMwavePause  = StringVar()  # Pause (s)
varTMwaveEnd    = StringVar()  # End (s)
#
varEXslit       = StringVar()  # Inc time (s)
varEMslit       = StringVar()  # Inc time (s)
#
varSpecimenDetails = StringVar()  # Description of sample
#
varEXstepsNm = StringVar()      # EX StepMotor steps per (nm)
varEMstepsNm = StringVar()      # EM StepMotor steps per (nm)
#
varPCTdone      = IntVar()      # % completion of scan
varPCTdone.set(45)     # testing: software completion % ;-)
#
MINnm = 200         # Minimum nanoMeters for monochrometer position
MAXnm = 1000        # Maximum nanoMeters for monochrometer position


#
#
# system and communication constants:
#
thisSys = sys.platform  # 'linux','win32,'cygwin','darwin'
firmwareVer = ''        # RetroSPEX_Rev-8  (for example)
print('This System: {}'.format(thisSys))
#
if thisSys == 'linux':
    portList = ['/dev/ttyACM0','/dev/ttyACM1', '/dev/ttyACM2', 'OFFLINE']
elif thisSys == 'win32':
    portList = list('COM'+str(x) for x in range(99,0,-1)).append('OFFLINE')
    # ports = ['COM99', 'COM98', ... 'COM2', 'COM1', 'COM0', 'OFFLINE']
else:
    msg_ = 'ERROR','Operating System not recognized: {}'
    messagebox.showifo(msg_.format(thisSys))
    sys.exit(0)
#
if thisSys == 'linux':
    #monoFont = font.Font(family='Ubuntu Mono', size=10)
    monoFont = font.Font(family='Ubuntu Mono', size=16)
    EOL = '\n'
    OKser = 1   # serial character sent OK. (number of characters sent > 0)
elif thisSys == 'win32':
    monoFont = font.Font(family='Miriam Fixed', size=10)
    EOL = '\r\n'
    OKser = 0   # serial character sent OK (no error).
else:
    messagebox.showifo('ERROR','Operating System not recognized: {}'.format(thisSys))
    sys.exit(0)
#
#

def setScanMode_FR(mode):   # Forward Reference for setting Scan Mode
    if jjltest:
        print('CALLED: setScanMode_FR(mode)  => pass')
    pass
#    
def setScanMode(mode):
    if jjltest:
        print('CALLED: setScanMode(mode) => setScanMode_FR(mode)')
    setScanMode_FR(mode)
    

def updatePlot_FR():    # Forward Reference FUNCTION NAME ... for updating Plot
    pass
#
def updatePlot(event=None):     # Call the function defined later on...
    updatePlot_FR()             # ... maps old references to the new routine

#===================
## Utility functions
#
#----
def nop():  # No OPeration (placeholder for function when none required)
    print('nop(): called.')
    return
    

#----
def notImplemented(msg):
    mBox.showwarning('NOTICE: Not Implemented',msg)
    return

blinkSpeed = [(50,2000), (2000,50), (100,100)]
#
# default speed is STATEstop (non-scanning)
blinkOnTime, blinkOffTime  =   blinkSpeed[STATEstop]

#----
def setScannerState(state):
    '''Blink rate changes with scannerState.'''
    global blinkSpeed, blinkOnTime, blinkOffTime, scannerState
    scannerState = state
    blinkOnTime, blinkOffTime  =   blinkSpeed[state]
    return

#----------------------------------------
# Set and Read High Voltage Power Supply
# 
# D 1 FFFF  -> 1000 v (neg)  Emission PMT
# 0 ~ 65535 -> 1000 v :  65.535 / volt
# 
# HV 1:
# SET:  [ 900 to E666] :: E666/FFFF -> 0.90000  (58982/65535)*1000 = 900.00
# READ: [BCD4 to  900] :: BCD4/D1B6 -> 0.90042  (48340/53686)*1000 = 900.42
# 
# 2.048/2.5 = 0.8192        ** ratio of DAC/ADC reference voltages
# 65.535 * 0.8192  = 53.686 ** ADC conversion divisor (53686) / D1B6
# 
# 
# HV 1:
# VOLTStoHEX = hex(int(volts * 65.535))[2:]
#                     900.0 * 65.535 => hex( int( 58982 ))[2:] = 'e666'
# HEXtoVOLTS  = int(setHV1str,16) /( 65.535 * 0.8192 )
#               (BCD4)  48340   /    53.686     =>   900.42
# 
#----
def VOLTStoHEX(voltStr):
    """voltStr = '-905.23' (string) -> 'E7BC' ({positive} Hex string)
    DAC: 1000.0 volts full scale (FFFF).
    (for setting DAC output)
    VOLTStoHEX('1000.0') => 'FFFF'
    VOLTStoHEX( '900.0') => 'E665' """
    print('VOLTStoHEX(voltStr) - voltStr: {}'.format(voltStr))
    s = '{:04x}'.format(int(abs(float(voltStr)) * 65.535 + 0.5)).upper()
    return s
#    
#----
def HEXtoVOLTS(ADChexStr):
    """ADChexStr = 'BCD4' ->  '-900' ({negative} string)
    ADC: 1000.0 volts full scale (D1B6).
    (for scaling ADC input)
    HEXtoVOLTS('D1B6') => '-1000'
    HEXtoVOLTS('BCD4') =>  '-900' """
    s = str(int(int(ADChexStr,16) / 53.686 + 0.5))
    if s != '0':
        s = '-' + s     # non-zero voltages are negative (power supply)
    return s
#   
#----
def updateTitle():
    '''Display com port, spectrometer firmware and System information
    on window title bar.'''
    msgSys  = ',   System: {}'.format(thisSys)
    msgPort = ',   Port: {}'.format(portName)
    msgSPEX = ',   Firmware: {}'.format(firmwareVer)
    siWin.wm_title( siTitle + msgSys + msgPort + msgSPEX)
    return
    
#----
def digitsOnly(text):
    s = ''
    for c in text:
        if c in string.digits:    
            s = s + c
    if s.strip() == '':
        s = '0'
    return str( int(s) )    # no leading zeros

#----
def floatOnly(text):
    '''get StringVar's value as float().'''
    point = False
    s = ''
    r = ''
    for c in text:
        if point == False:      # no decimal yet
            if c in string.digits:
                s = s + c
            elif c == '.':
                point = True
        else:
            if c in string.digits:
                r = r + c
    # supress leading zeros
    s = s.lstrip('0')
    # but keep at least one zero(!)
    if len(s) == 0:
        s = '0'
    # resolution limited to mS
    if len(r) > 3:
        r = r[0:3]
    s = s+ '.' +r
    return s

#----
def getVarInt(v):
    '''get StringVar's value as int().'''
    s = v.get()
    if s.strip() == '':
        return 0
    return int(s)

#----
def getVarFloat(v):
    '''get StrinvVar's float value.'''
    s = v.get()
    #print('getVarFloat(v): s={}, v={}'.format(s,v))
    if s.strip() == '':
        return 0.0
    return float(s)
 
#----
def setFocus(obj):
    obj.focus_set()
    return
    
#----
def panelButton(txt):   # received a message; front panel button push/release
    '''Front Panel Button: unsolicited message.
    "# 0" => Released, "# 1" => Pushed'''
    #
    # only take action on button pushed in
    if txt.endswith('1'):   # button pushed
        # testing: simulate some ACTion on button pushed in
        if pausetest:
            print('panelButton(txt): PRESSED: {}'.format(txt))
            if scannerState == STATEpause:
                setScannerState(STATEscan)
            else:
                setScannerState(STATEpause)
        else:
            # ignore if not TMscan !
            if varScanMode.get() == TMscan:
                if scannerState == STATEscan:
                    setScannerState(STATEpause)
                elif scannerState == STATEpause:
                    setScannerState(STATEscan)
    # ignore Button releases
    else:
        if pausetest:
            print('panelButton(txt): RELEASE: {}'.format(txt))
    return  
    
        
    
#----
def toggleBtnVar(var, btn, iconOff, iconOn):
    '''Toggle boolean state of Button and set matching icon.'''
    if var:
        #print('toggleBtnVar(var, btn, iconOff, iconOn): var={}'.format(var))
        newVar = False
        btn['image'] = iconOff
    else:
        newVar = True
        btn['image'] = iconOn
    return  newVar
    
#----
def getDateToday():
    '''2015-02-14'''
    t = time.localtime()
    return '{}-{:02d}-{:02d}'.format(t[0],t[1],t[2])
    
#----
def timeNow():
    '''2014-02-14_11:14:47'''
    t = time.localtime()
    s = '{}-{:02d}-{:02d}_{:02d}:{:02d}:{:02d}'.format(t[0],t[1],t[2],t[3],t[4],t[5])
    return s

#----
def setPlotTitle():
    '''Plot Title is 2 lines: 
    Top;    filename where scan data was saved (post acquisition).
    Second; filename where Reference data was loaded from. (background).'''
    #print('setPlotTitle(): {}'.format(varRefFileName.get()))
    # Top:  Scan Data Save File
    if varScanDataFileName.get() == '':
        title = timeNow() + '_' + scanName[ varScanMode.get() ] + ':_' + \
                varSpecimenDetails.get()[0:40]
    else:
        title = varScanDataFileName.get()
    # Bot:  Reference Data Load File
    title += '\n'       # Bottom (of two) lines
    if varRefFileName.get() != '':
        title += 'Reference Data File:   ' + varRefFileName.get()
    #
    ax.set_title( title )
    return
    
parseError = False

#----
def parseSerial():
    '''
    '''
    global serInLines, parseError
    global crQ, crQbusy, crQcmd, crQrsp, crQnxt
    if len(serInLines) > 0 :
        #
        txt = serInLines.pop(0).strip() # grab input line
        # print('parseSerial(): "{}"'.format(txt))
        #
        ## = Error message
        if txt == 'e':  # ERROR message from RetroSPEX
            # was 'e' expected ??
            if crQrsp == 'e':    # this is an expected 'error' (synchronizing)
                crQnxt()            # execute 'nxt' function
                parseError = False  # clear Error flag
                crQbusy = False     # command executed, allow next command
            else:   # unexpected error
                if parseError:      # don't resend command more than once
                    parseError = False
                    crQbusy = False     # command IGNORED, allow next command
                else:
                    parseError = True   # repeat sent command one time
                    print('parseSerial(): error: "{}"'.format(txt))
                    print('parseSerial(): resend cmd: "{}"'.format(crQcmd))
                    serBufLoad(crQcmd + EOL)  # ... put command into 'send queue'
        #
        ## = COMPLETE ECHO OF ISSUED COMMAND (i.e.  "L 0", "L 1", "T #", ...)
        elif txt == crQrsp:    # response to previous command ?
            #
            if crqtest:
                print('parseSerial(): rsp: "{}"'.format(crQrsp))
                print('parseSerial(): execute nxt: {}'.format(crQnxt))
            crQnxt()            # execute 'nxt' function
            crQbusy = False     # command executed, allow next command
        #
        ## = ADC => returned voltage
        elif txt.startswith('A ') and crQcmd == 'A':    # Read Voltage
            #
            crQrsp = txt        # 'txt' response is in correct format
            if crqtest:
                print('parseSerial(): rsp: "{}"'.format(crQrsp))
                print('parseSerial(): execute nxt: {}'.format(crQnxt))
            crQnxt()            # execute 'nxt' function
            crQbusy = False     # command executed, allow next command
        #
        ## = FRONT PANEL BUTTON => PUSH ( '# 1' ) / RELEASE ( '# 0' )
        elif txt.startswith('# '):  # Front Panel Button action
            #
            # NOTE: UNSOLICITED COMMAND => NOT A RESPONSE TO COMMAND ISSUED
            #
            print('parseSerial(): BUTTON: "{}"'.format(txt))
            panelButton(txt)       # 'txt' = button's message
        #
        ## = UNRECOGNIZED RESPONSE
        else:
            #
            if crqtest:
                print('parseSerial(): unknown: "{}"'.format(txt))
                print('parseSerial(): LINE - ignored <for now>')
            crQbusy = False     # command executed, allow next command
    #
    return

# BONtime = 0
# BONlist = []

#----
def readSerial():
    global serInBuffer, serInLines, crQ, blinkOnTime
#     global BONtime, BONlist # diagnose lengthening of blink on time
    full = True
    while full:
        c = serialPort.read()   # attempt to read a 'byte' from Serial
        #
        # was anything read ?
        if c == b'':
            if comtest:
                print('^',end='')
            full = False                # no serial data available now
            siWin.after(20, readSerial) # check serial again soon
            return
        else:
            c = chr( ord(c)%128 )       # 'bytes' (7-bit) to 'string' type
        
        # check if character is a delimeter
        if c == '\r':
            continue # don't want returns. ignore it
        
        if c == '\n':
            # the buffer contains an entire line - less the 'newline'
            # proccess the line now.
            if crqtest:
                print('LINE: {}'.format(serInBuffer))
#             if serInBuffer.startswith('L 1'):
#                 Btime = int((time.time() - BONtime)*1000)
#                 BONlist.append(Btime)
#                 if len(BONlist) > 2000:
#                     f=open('testTimes.txt','w')
#                     f.write(str(BONlist))
#                     f.close()
#                     print('BONlist(): Closed')
#                     sys.exit(0)
#                 print('Btime: {}ms  len(crQ): {}  blinkOnTime: {}'.format(Btime, len(crQ), blinkOnTime))
            serInLines.append(serInBuffer)  # add to list of input lines
            serInBuffer = ''                # empty the buffer
            #siWin.update_idletasks()
            siWin.after(20, parseSerial)     # respond to input line
        else:
            serInBuffer += c # add to the buffer
    #siWin.update_idletasks()
    siWin.after(20, readSerial) # check serial again soon
    return


#----
def xmitSerial():
    global serOutBuffer,serialPort,serOutReady
    if comtest:
        print('.',end='')
#     if serOutReady:
#         print('.',end='')
    while serOutReady and len(serOutBuffer) > 0:    # Anything to send out?
        # send byte
        c = serOutBuffer[0:1]
        # print('xmitSerial(): send byte {}'.format(c))
        try:
            nSent = serialPort.write( c )
        except:
            mBox.showerror('Communication Failure','Lost connection to RetroSPEX')
            sys.exit(0)
        # print('nSent: {}'.format(nSent))
        if nSent != OKser:  # show transmit error
            if comtest:
                patrn = 'xmitSerial({}),ERROR: status => {}, retry.'
                print(patrn.format(c,repr(nSent)))
        else:   # GOOD send
            if comtest:
                patrn = 'xmitSerial({}), SENT: status => {}.'
                print(patrn.format(c,repr(nSent)))
            # remove sent character from the buffer
            serOutBuffer = serOutBuffer[1:] 
    return

#----
def serBufLoad(text):
    global serOutBuffer
    #
    # convert 'string' characters to 'bytes' for output
    serOutBuffer = serOutBuffer + text.encode() # add to transmit buffer
    if crqtest:
        print('serBufLoad(text): serOutBuffer: {}'.format(serOutBuffer))
    xmitSerial()
    return

    
#----
def writePositions():
    '''Write monochrometer positions to "positions.txt" file.'''
    #
    global varLiveEXpos,varLiveEMpos
    #
    data = 'EX: ' + varLiveEXpos.get() + ' EM: ' + varLiveEMpos.get() + '\n'
    fo = open('positions.txt','w')
    fo.write(data)
    fo.close()
    return    
    
#----
def readPositions():
    '''Recover monochrometer positions from "positions.txt" file.'''
    #
    global varLiveEXpos,varLiveEMpos
    #
    try:        # one line file:  "EX: nnnn EM: mmmm"
        tmpFile = open('positions.txt').read().splitlines()
        for s in tmpFile:
            t = s.split()
            if len(t) == 4 and t[0] == 'EX:' and t[2] == 'EM:':
                varLiveEXpos.set(t[1])
                varLiveEMpos.set(t[3])
        tmpFile = None
    except:
        varLiveEXpos.set('0')
        varLiveEMpos.set('0')
        writePositions()
    return
        
    
def dataFileREAD():
    '''Read Data file, seperate into lists of header and data.'''
    #
    global inputFileHdr   # Header section from fileLoad
    global inputFileData  # Data   section from fileload
    #
    inputFileHdr = []
    inputFileData = []
    #
    dataFileTypes = [("Data ", ("*.txt","*.TXT")), ]
    dataDir = '~/SCANS'
    fInp = filedialog.askopenfilename(filetypes = dataFileTypes
                                     ,initialdir=dataDir)
    # save file name for Plot Display
    varRefFileName.set( fInp ) 
    setPlotTitle()          # update Title on plot
    print('RefFileName: {}'.format(fInp))
    #
    tmpFile = open(fInp).read().splitlines()
    #
    header = True   # looking for header lines first
    #
    for line in tmpFile:    # examine each line in list
        if header:
            if line.startswith('...'):  # end of Header line mark
                header = False
            else:
                inputFileHdr.append(line.strip())  # save Header lines
        else:
            if line.startswith('___'):  # end of Data line mark
                break
            else:
                inputFileData.append(line.strip()) # save data lines
    tmpFile = None  # discard temp file data now
    return



#
## command/response Queue
#
crQ = []            # PATTERN OF "entry": [cmd,resp,nxt]
                    # where; cmd = "D 0 0000", rsp = "D 0 0000", nxt = <func>
                   
#----
def crQsend():
    '''If no command is active, start sending one to RetroSPEX.'''
    global crQ, serOutReady, crQbusy, crQcmd, crQrsp, crQnxt
    global BONtime  # diagnose blink ON time
    if not crQbusy and len(crQ) > 0:
        crQbusy = True          # now, busy doing the command below:
        crQlist = crQ.pop(0)        # hold command list: [ cmd, rsp, nxt ]
        crQcmd      = crQlist[0]    # ... command being executed
        if crQcmd == "L 1":  # blink ON
            BONtime = time.time()
        crQrsp      = crQlist[1]    # ... response being awaited
        crQnxt      = crQlist[2]    # ... function to execute upon response.
        serBufLoad(crQcmd + EOL)    # ... put command into 'send queue'
    else:
        siWin.after(200, crQsend)        # check again later on
    return

    
def crQappend(entry):
    '''Put "entry" into the crQ.
    Trigger sending to RetroSPEX.'''
    global crQ,serOutReady
    #
    crQ.append(entry)   # append this command to Queue
    if crqtest:
        print('crQappend(entry): {!r}'.format(entry))
    # display new queue contents
    if crqtest:
        print('crQappend(entry): crQ:')
        for i in crQ:
            print('\t{}'.format(i))
    crQsend()           # insure command sending is active
    return


#----
def crQnext(cmd):
    '''Response to sent command has been recieved,
    take whatever next action (if any) is specified.'''
    global crQ
    #TODO add 'chain' to next command in crQ
    print("crQnext(): TODO add 'chain' to next command in crQ")
    return

#dbgOnTime = 0
#----
def blinkOnDelay():
    '''Set time to leave LED ON'''
    siWin.after(blinkOnTime, cmdL_BlinkOFF)   # delay for ON time
    return

#----
def blinkOffDelay():
    '''Set time to leave LED OFF'''
    siWin.after(blinkOffTime, cmdL_BlinkON)   # delay for OFF time
    return
    
#----
def cmdL_BlinkON():
    '''Turn LED on for this portion of 'blink cycle'.'''
    #
    crQappend( ['L 1', 'L 1', blinkOnDelay] )   # add to crQ for sending 
    return

#----
def cmdL_BlinkOFF():
    '''Turn LED off for this portion of 'blink cycle'.'''
    #
    crQappend( ['L 0', 'L 0', blinkOffDelay] )   # add to crQ for sending 
    return

#----
def doCmdA_HVupdate():
    '''Receive converted (ADC) High Voltage levels and update Live Data.'''
    global crQ, crQrsp
    if jjltest:
        print("doCmdA_HVupdate(): update Live Data HV levels")
    #
    txt = crQrsp.split(' ')     # seperate into ["A", <hex EM>, <hex REF>]
    if jjltest:
        print('doCmdA_HVupdate(): crQrsp: {!r}'.format(txt))
    #
    hvem  = HEXtoVOLTS(txt[1])
    hvref = HEXtoVOLTS(txt[2])
    if jjltest:
        print('doCmdA_HVupdate(): hvem: {}, hvref: {}'.format(hvem, hvref))
    #
    varLiveEMhv.set(hvem)       # Live EM PMT high voltage (v)
    varLiveREFhv.set(hvref)     # Live REF PMT high voltage (v)
    #
    return


#----
def cmdA_HVread():
    '''Read converted (ADC) High Voltage levels as HEX.'''
    global crQ
    if jjltest:
        print("cmdA_HVread(): read converted HV levels (as Hex strings).")
    #
    crQappend( ['A', 'A # #', doCmdA_HVupdate] )   # add to crQ for sending 
    return


#----
def cmdH_HVconv():
    '''Convert (ADC) High Voltage levels to RetroSPEX registers.'''
    #
    if True: #jjltest:
        print("cmdH_HVconv(): request ADC conversion of HV voltages.")
    #
    crQappend( ['H', '! 01', cmdA_HVread] )   # add to crQ for sending 
    return
    

#----
def cmdD_HVon():
    '''Set High Voltage to operating voltage levels.
    cmd0 = "D 0 <hexV>"
    cmd1 = "D 1 <hexV>" '''
    #
    cmd0 = "D 0 " + VOLTStoHEX(varREFhv.get())
    crQappend( [ cmd0, cmd0, nop] )   # add to crQ for sending 
    #
    cmd1 = "D 1 " + VOLTStoHEX(varEMhv.get())
    crQappend( [ cmd1, cmd1, cmdH_HVconv] )   # add to crQ for sending
    return

#----
def cmdD_HVoff():
    '''Set High Voltage to zero volt levels.
    "D 0 0000" = HV supply for Reference PMT
    "D 1 0000" = HV supply for Emission PMT'''
    #
    crQappend( ['D 0 0000', 'D 0 0000', nop] ) 
    crQappend( ['D 1 0000', 'D 1 0000', cmdH_HVconv] ) 
    return

#----
def cmdT_setIntTimer():
    '''Set "Integration Timer".
    "T <time-Hex>"
    <time-Hex> is time in ms (integer, 47-bit Hex)
    "T 00000005" => "T 00000005" (5 ms)
    "T 000003E8" => "T 000003E8" (1,000 ms)'''
    #
    # integration time (currently) is varTMinc.get()  {stringVar}
    # integration time (seconds) => integer-integration-time-ms-hex-string
    cmd = 'T {:08x}'.format(int(abs(float(varTMinc.get())) * 1000 + 0.5)).upper()
    crQappend( [cmd, cmd, nop] ) 
    return
    


## Serial - ensure non-blocking
#    --  NOTE: rtscts=1  hardware handshake for 'ready' with data
#
# establish serial module
# baudrate for RetroSPEX is 115200 (ArduinoDue max)
#
# look for serial port
def portTry(name):
    '''Test 'name' to see if it goes to RetroSPEX.'''
    global serialPort, firmwareVer, serInBuffer, serInLines, serOutReady
    #TODO add timeout for testing a found serial port in portTry()
    print("TODO add timeout for testing a found serial port in portTry()")
    if comtest:
        print('\tportTry(name): {}'.format(name))
    try:
        serialPort = serial.Serial(port=name 
                                ,baudrate=115200
                                ,timeout=0
                                ,rtscts=1
                                ,dsrdtr=True
                                ,writeTimeout=0) 
#         #serialPort.open()  just opened !
#         serialStatus = serialPort.isOpen()
#         print('\nportTry({}): serialPort.isOpen = {}'.format(name,serialStatus))
#         return serialStatus
        if comtest:
            print('\tOPEN...')
    except:
#         print('portTry(name): NOT portName: {}'.format(name))
#         return False
        if comtest:
            print('\tCLOSED')
        return False
    #
    buf = ''    # input buffer for port testing
    for trial in range(10):
        if comtest:
            print('\t\ttrial={}'.format(trial))
        for t in range (43):
            i = b''
            while i == b'':     # SKIP NULL CHARACTERS
                i = serialPort.read()
#                 if i == b'':
#                     if comtest:
#                         print('\t\t read(): NULL')
            c = chr( ord(i)%128 )
            if comtest:
                print('\t\t ord(c):{}, chr( ord(c)%128 ):{}'.format(ord(i),c))
            if c == '\n':
                if buf.startswith('RetroSPEX'):     # This is RetroSPEX !!
                    firmwareVer = buf[:]        # save for Version info.
                    updateTitle()               # Title includes RetroSPEX Rev-#
                    serInBuffer = ''
                    serInLines = []
                    serOutReady = True          # RetroSPEX is ready !
                    serialPort.write( b'\n' )   # send a response byte
                    readSerial()                # start monitoring input
                    return True
                else:
                    buf = ''
            else:
                buf = buf + c
            if comtest:
                print('\t\t buf: {}'.format(buf))
    return False
        

    
def portScan():    
    '''Search for serial USB port for Spectrometer, or "OFFLINE".'''
    global serialPort, portList, portName, serInLines
    #
    for portName in portList :
        if portName != 'OFFLINE':
            if portTry(portName):   # a serialPort found
                readSerial()        # start monitoring serial input
                if jjltest:
                    print('\nFOUND serialPort={}'.format(serialPort))
                    print('FOUND portName: {}'.format(portName))
                updateTitle()   # new "Port" name
                return
        else:   # end of list 'OFFLINE' reached, no port found
            if True: #comtest:
                print('Serial Port not found... Operating OFFLINE')
                # show ports tried
                for name in portList[0:-1]:
                    print('tried: {}'.format(name))
            #
            # operating OFFLINE
            updateTitle()   # new "Port" or "OFFLINE"
            return
    title = siTitle + ',     Port: {} on System: {}'
    siWin.wm_title( title.format(portName, thisSys))
    return
    

#
## 'sanityCheck' functions
#
# COMPARISONS:
# Within [min <= var <= max]
# Order  [var1 < var2]
# Min    [min <= var]
#
# Button lookup dictionary   -   defined as buttons are created below
btnLookup = {}      #  entries of form:  'EXS':<EX-Start_button>   
#                                        'EXE':<EX-END_button>
#              test      variable        min    max      EntryType
chkEntVal =[ [['Within', varEXwaveStart, MINnm, MAXnm] , 'EXS' ]
           , [['Within', varEXwaveEnd,   MINnm, MAXnm] , 'EXE' ]
           , [['Order' , varEXwaveStart, varEXwaveEnd] , 'EXE' ]
           , [['Min'   , varEXinc,   1]            , 'EXI' ]
           , [['Within', varEMwaveStart, MINnm, MAXnm] , 'EMS' ]
           , [['Within', varEMwaveEnd,   MINnm, MAXnm] , 'EME' ]
           , [['Order' , varEMwaveStart, varEMwaveEnd] , 'EME' ]
           , [['Min'   , varEMinc,   1]            , 'EMI' ]
           , [['Min'   , varTMwaveEnd, 0.100]          , 'TME' ]
           , [['Order' , varTMwavePause, varTMwaveEnd] , 'TME' ]
           , [['Min'   , varTMinc, 0.001]          , 'TMI' ]
           ]
#
def scanSanityCheck(warn = False):
    '''Check that measurement parameters have "sane" values.
    If not color Entry field WARNC color.
    If "warn" argument is True also generate popup message.'''
    #
    isSane = True       # start assuming that no errors were found ;-)
    #
    for e in chkEntVal:
        test,entryType = e     # get test list and Entry-Type
        #
        # are any of these Entry objects 'DISABLED'?
        # - don't check values for disabled Entry fields
        if btnLookup[entryType]['state'] == DISABLED:
            continue    # try next test
        #
        if test[0] == 'Min':    # is entry at least equal to the minimum
            #print('sanity()"Min":{}; {}'.format(test,entryType))
            #if jjltest:
            #print('scanSanityCheck()...: test[0]={}'.format(test[0]))
            #print('.........entryType={}'.format(entryType))
            if entryType[0] == 'T':     # float value for Time settings
                #print('sanity()"entryType": {}'.format(entryType))
                var = getVarFloat(test[1])
                #print('sanity() var: {}'.format(var))
            else:
                var = getVarInt(test[1])
            #if entryType == 'TMI':
            #    print('TMI:.........var={} < min={}'.format(var,test[2]))
            if var < test[2]:   # BELOW minimum = Error
                isSane = False
                bgColor = WARNC
            else:
                bgColor = 'white'
        elif test[0] == 'Within':    # entry not OUTSIDE limits
            #if jjltest:
            #print('scanSanityCheck()...: test[0]={}'.format(test[0]))
            #print('.........entryType={}'.format(entryType))
            var = getVarInt(test[1])
            #print('.........var={} < min={}'.format(var,test[2]))
            limLow = test[2]
            limHi  = test[3]
            #print('.........limLow={} < limHi={}'.format(limLow,limHi))
            if var < limLow or var > limHi:   # outside range
                isSane = False
                bgColor = WARNC
            else:
                bgColor = 'white'
        elif test[0] == 'Order':    # entry 1 less-than entry 2
            #if jjltest:
            #print('scanSanityCheck()...: test[0]={}'.format(test[0]))
            #print('.........entryType={}'.format(entryType))
            if entryType[0] == 'T':     # float value
                print('scanSanityCheck() #318... test[1]={}, '
                      'test[2]={}'.format(test[1],test[2]))
                var1 = getVarFloat(test[1])
                var2 = getVarFloat(test[2])
                print('scanSanityCheck() #322... var1={}, var2={}'.format(
                      var1,var2))
            else:
                var1 = getVarInt(test[1])
                var2 = getVarInt(test[2])
            #print('.........var1={} < var2={}'.format(var1,var2))
            if var1 >= var2:   # improper order
                isSane = False
                bgColor = WARNC
            else:
                bgColor = 'white'
        #
        # set the selected color for the Entry object
        btnObj = btnLookup[entryType]
        btnObj['bg'] = bgColor     # set button color
    return isSane
                     

#
## 'legacy' data file input functions
    
def dataFileMGET():
    '''Read Data file, seperate into header and data.
    Parse header into measurement parameters.
    Set the parameters for taking another scan.
    '''
    global inputFileHdr   # Header section from fileLoad
    #
    dataFileREAD()          # read in data file, prepare header list
    #
    # Parse Header information - "classic format"
    # Emission only - for now
    scanIs = None
    for line in inputFileHdr:
        if line.startswith('Emission Scan'):
            scanIs = EMscan
            break
    #
    if scanIs == EMscan:  # restore measurement variables
        #
        setScanMode(EMscan)
        #
        #    varEMwaveStart  = StringVar()  # Emission Start Wavelength nm
        #    varEMwaveEnd    = StringVar()  # Emission End   Wavelength nm
        #    varEMwaveInc    = StringVar()  # Emission Inc   Wavelength nm
        #    varTMinc    = StringVar()  # Time Inc time S
        #    varEXwaveStart  = StringVar()  # Excitation Start Wavelength nm
        #
        for line in inputFileHdr:
            if line.startswith('Start '):   # Start , End
                s,e = line.split(',')
                s = s.split(' ')[1]     # "Start 5.000000e+002"
                n = int( float( s))
                varEMwaveStart.set( str(n))
                #
                e = e.strip()
                e = e.split(' ')[1]     # "End 7.000000e+002"
                n = int( float( e))
                varEMwaveEnd.set( str(n))
                continue
            if line.startswith('Increment '):
                c,t = line.split(',') 
                c = c.split(' ')[1]     # "Increment 1.000000e+000"
                n = int( float( c))
                varEMwaveInc.set( str(n))
                #
                t = t.strip()
                t = t.split(' ')[2]     # "Integration Time 1.000000e-001"
                n = float( t)
                varTMinc.set( str(n))
                continue
            if line.startswith('Excit Mono Slits:'):
                continue
            if line.startswith('Excit Mono'):
                x = line.split(' ')[2]   # "Excit Mono 4.880000e+002"
                n = int( float( x))
                varEXwaveStart.set( str(n))
    else:
        #    if scanIs != EMscan:  # Error
        if jjltest:
            print("Can't handle non-Emission Scan yet.")
        sys.exit(0)
    scanSanityCheck()
    return
            
    
def dataFileLOAD():
    '''Read Data file, seperate into header and data.
    Parse header into measurement parameters.
    Parse data into x,y values for plotting.
    '''
    global inputFileData  # Data   section from fileload
    global backgroundDataX       # X value sample was taken at (wavelength / time)
    global backgroundDataY       # Y value of sample - PMT counts
    #
    dataFileMGET()          # Read data file, setup measurement parameters.
    #
    backgroundDataX = []
    backgroundDataY = []
    #
    for line in inputFileData:
        pos,val = line.split('\t')
        backgroundDataX.append( int( float( pos )))
        backgroundDataY.append( float( val ))
    updatePlot()   

#
## 'dayfile.txt' - functions for recording Experimental Plan
#
#
# 'dayfile.txt' format:
#        
#   DATE: 2015-01-29
#   Meaning of Experiment:
#   #m#...  (text: additional lines of meaning)
#   Slit Widths EX:  2  (integer in nm)
#   Slit Widths EM:  2  (integer in nm)
#   Bulb Intensity:  ?? (integer in ??)
#   Notebook page:   ?? (text)
#   Other comments:
#   #c#...  (text: additional lines of comments)
#
#     dayFileData = []  # Data   section from fileload
#     #
#     varDayDate     = StringVar()  # Date this data was entered
#     varDayMeaning1 = StringVar()  # Meaning of Experiment
#     varDayMeaning2 = StringVar()  # Meaning of Experiment
#     varDayMeaning3 = StringVar()  # Meaning of Experiment
#     varEXslit      = StringVar()  # Excitation slit size nm
#     varEMslit      = StringVar()  # Emission   slit size nm
#     varDayBulb     = StringVar()  # Measured Bulb Intensity
#     varDayNotebook = StringVar()  # Notebook Page for Experiment Data
#     varDayOther1   = StringVar()  # Other comments
#     varDayOther2   = StringVar()  # Other comments
#     varDayOther3   = StringVar()  # Other comments
#
def makeDayFile():
    '''Create new GUI screen for entering Experimental Data.
    This data is constant for each day and recorded with data scans.'''
    #
    if jjltest:
        print('makeDayFile()')
    #
    varDayDate.set( getDateToday() )
    #
    froot = Toplevel()
    froot.title('Edit Experiment Information for {}'.format(varDayDate.get()))
    froot.geometry(transGeom)
    #siWin.withdraw()
    #
    # ========
    #
    #-------
    frootFrame = Frame(froot, bg = TANBG)
    frootFrame.grid()
    #-------
    dayTopFrame = LabelFrame(frootFrame, bg = TANBG, borderwidth=4
                            ,text='  Meaning of Experiment:  '
                            , font=monoFont14)
    dayTopFrame.grid(row = 0, padx=4, pady=4, sticky=NSEW)
    #
    #
    #-------
    varDayMeaning1.set('')
    dayMeanEnt1 = Entry(dayTopFrame, textvariable=varDayMeaning1
                      ,border=2, relief=SUNKEN, width=60
                      ,font=monoFont14 )
    dayMeanEnt1.grid(row=1, padx=4, pady=0, sticky=EW)
    dayMeanEnt1.focus_set()
    #-------
    varDayMeaning2.set('')
    dayMeanEnt2 = Entry(dayTopFrame, textvariable=varDayMeaning2
                      ,border=2, relief=SUNKEN, width=60
                      ,font=monoFont14 )
    dayMeanEnt2.grid(row=2, padx=4, pady=0, sticky=EW)
    dayMeanEnt1.bind("<Return>", lambda e: setFocus(dayMeanEnt2))
    #-------
    varDayMeaning3.set('')
    dayMeanEnt3 = Entry(dayTopFrame, textvariable=varDayMeaning3
                      ,border=2, relief=SUNKEN, width=60
                      ,font=monoFont14 )
    dayMeanEnt3.grid(row=3, padx=4, pady=0, sticky=EW)
    dayMeanEnt2.bind("<Return>", lambda e: setFocus(dayMeanEnt3))
    #
    # ========
    #
    #-------
    dayMidFrame = Frame(frootFrame, bg = TANBG, borderwidth=0)
    dayMidFrame.grid(row = 1, sticky=NSEW)
    #
    # Slit Width EX:
    #-------
    daySlitExLab = Label(dayMidFrame, text='Slit Width EX:'
                      , font=monoFont14, bg = TANBG )
    daySlitExLab.grid(row=0, sticky=W)
    #-------
    daySlitExEnt = Entry(dayMidFrame, textvariable=varEXslit
                      ,border=2, relief=SUNKEN, width=20
                      ,font=monoFont14 )
    daySlitExEnt.grid(row=0, column=1, padx=4, pady=4, sticky=E)
    dayMeanEnt3.bind("<Return>", lambda e: setFocus(daySlitExEnt))
    #
    # Slit Width EM:
    #-------
    daySlitEmLab = Label(dayMidFrame, text='Slit Width EM:'
                      , font=monoFont14, bg = TANBG )
    daySlitEmLab.grid(row=1, sticky=W)
    #-------
    daySlitEmEnt = Entry(dayMidFrame, textvariable=varEMslit
                      ,border=2, relief=SUNKEN, width=20
                      ,font=monoFont14 )
    daySlitEmEnt.grid(row=1, column=1, padx=4, pady=4, sticky=E)
    daySlitExEnt.bind("<Return>", lambda e: setFocus(daySlitEmEnt))
    #
    # Bulb Intensity:
    #-------
    dayBulbIntLab = Label(dayMidFrame, text='Bulb Intensity:'
                      , font=monoFont14, bg = TANBG )
    dayBulbIntLab.grid(row=2, sticky=W)
    #-------
    dayBulbIntEnt = Entry(dayMidFrame, textvariable=varDayBulb
                      ,border=2, relief=SUNKEN, width=20
                      ,font=monoFont14 )
    dayBulbIntEnt.grid(row=2, column=1, padx=4, pady=4, sticky=E)
    daySlitEmEnt.bind("<Return>", lambda e: setFocus(dayBulbIntEnt))
    #
    # Notebook Page:
    #-------
    dayNbPageLab = Label(dayMidFrame, text='Notebook Page:'
                      , font=monoFont14, bg = TANBG )
    dayNbPageLab.grid(row=3, sticky=W)
    #-------
    dayNbPageEnt = Entry(dayMidFrame, textvariable=varDayNotebook
                      ,border=2, relief=SUNKEN, width=20
                      ,font=monoFont14 )
    dayNbPageEnt.grid(row=3, column=1, padx=4, pady=4, sticky=E)
    dayBulbIntEnt.bind("<Return>", lambda e: setFocus(dayNbPageEnt))
    #
    # Other Comments:
    #-------
    dayBotFrame = LabelFrame(frootFrame, bg = TANBG, borderwidth=4
                    ,text='  Other comments:  ', font=monoFont14)
    dayBotFrame.grid(row = 2, padx=4, pady=4, sticky=NSEW)
    #-------
    dayOtherEnt1 = Entry(dayBotFrame, textvariable=varDayOther1
                       ,border=2, relief=SUNKEN, width=60
                       ,font=monoFont14 )
    dayOtherEnt1.grid(padx=4, pady=0, sticky=EW)
    dayNbPageEnt.bind("<Return>", lambda e: setFocus(dayOtherEnt1))
    #-------
    dayOtherEnt2 = Entry(dayBotFrame, textvariable=varDayOther2
                       ,border=2, relief=SUNKEN, width=60
                       ,font=monoFont14 )
    dayOtherEnt2.grid(padx=5, pady=0, sticky=EW)
    dayOtherEnt1.bind("<Return>", lambda e: setFocus(dayOtherEnt2))
    #-------
    dayOtherEnt3 = Entry(dayBotFrame, textvariable=varDayOther3
                       ,border=2, relief=SUNKEN, width=60
                       ,font=monoFont14 )
    dayOtherEnt3.grid(padx=6, pady=0, sticky=EW)
    dayOtherEnt2.bind("<Return>", lambda e: setFocus(dayOtherEnt3))
    #
    # ========
    #
    def makeDayFileDone(root=froot):
        #siWin.deiconify()
        print('makeDayFileDone(root=froot)')
        #print('makeDayFileDone(root=froot): [A]')
        froot.destroy()
        #print('makeDayFileDone(root=froot): [B]')
        return
    #
    #-------
    dayButFrame = Frame(frootFrame, bg = TANBG, borderwidth=4)
    dayButFrame.grid(row = 3, padx=2, pady=2, sticky=NSEW)
    #-------
    dayButBut = Button(dayButFrame, bg = TANBG, borderwidth=4
                      ,text = 'DONE', command = makeDayFileDone
                      ,activebackground=ACTIVB, font=monoFont16)
    dayButBut.grid()
    dayOtherEnt3.bind("<Return>", lambda e: setFocus(dayButBut))
    dayButBut.bind("<Return>", makeDayFileDone)
    #
    froot.transient(siWin)
    froot.grab_set()
    siWin.wait_window(froot)
    #
    # ========  NOW write out the data that was entered
    #
    dayFileData = [ 'DATE: ' + getDateToday()
                  , 'Meaning of Experiment: '
                  ]
    dayFileData.append( '# ' + varDayMeaning1.get() )
    dayFileData.append( '# ' + varDayMeaning2.get() )
    dayFileData.append( '# ' + varDayMeaning3.get() )
    dayFileData.extend(
                  [ 'Slit Widths EX: ' + varEXslit.get()
                  , 'Slit Widths EM: ' + varEMslit.get()
                  , 'Bulb Intensity: ' + varDayBulb.get()
                  , 'Notebook page: '  + varDayNotebook.get()
                  , 'Other comments: '
                  ] )
    dayFileData.append( '# ' + varDayOther1.get() )
    dayFileData.append( '# ' + varDayOther2.get() )
    dayFileData.append( '# ' + varDayOther3.get() )
    #
    #
    dayf = open('dayfile.txt','w')
    dayf.write( '\n'.join(dayFileData) )
    dayf.close()
    #
    print('makeDayFile(): CREATED')
    print('dayFileData: {}'.format(dayFileData))
    return

    
#
def checkDayFile():
    '''Read 'dayfile.txt' and if not created today, update it.'''
    global dayFileData
    #
    try:
        dayf = open('dayfile.txt','r')
    except:
        print('dayfile.txt does not exist, CREATE (and write) it.')
        makeDayFile()
        return
    #
    # Check that the day file is for TODAY's date
    dayFileData = dayf.read().splitlines()
    dayf.close()
    # file have data ?
    if len(dayFileData)<1:  # not one line !
        makeDayFile()       # create a new file
        return
    # examine the previous date
    #print('len(dayFileData): {}'.format(len(dayFileData)))
    today = dayFileData[0]
    #print('checkDayFile(): dayFile.txt, line #1: {}'.format(today))
    #
    date = dayFileData[0].strip()   # look at first line of file
    #print('checkDayFile() READ: {}'.format(date))
    if date.startswith( 'DATE: ' + getDateToday()) :
        print('checkDayFile() CURRENT')
        return      # file has current data
    # create a new file
    makeDayFile()   
    return


#
## Settings Read (default settings, etc.) for measurement
#
def readSettings():
    '''Read 'settings.txt' and recover default values.'''
    if jjltest:
        print('readSettings()')
    #
    # First set these to:
    # "Factory Default Settings"  
    #   (if no others are established, i.e. first run of software)
    #   "EXinc:        1"    # Setting EX Inc   Wavelength (nm)
    varEXinc.set('1')
    #   "EMinc:        1"    # Setting EM Inc   Wavelength (nm)
    varEMinc.set('1')
    #   "TMinc:        0.1"  # Setting TM Inc   time (s)
    varTMinc.set('0.1')
    #
    # Site Configuration 'factory defaults'
    #   "varEXslit:    2.9"  # Setting EX slit width (nm)
    varEXslit.set('2.9')
    #   "varEMslit:    2.9"  # Setting EM slit width (nm)
    varEMslit.set('2.9')
    #   "EMhv:        -900"  # Setting EM PMT high voltage (v)
    varEMhv.set('-900')
    #   "REFdiode:       0"  # Setting REF DIODE Gain setting [0,1,2,3]
    varREFdiodeG.set('0')
    #   "REFhv:       -450"  # Setting REF PMT high voltage (v)
    varREFhv.set('0')
    # CALIBRATION SETTINGS:
    #   "EXstepsNm:    50"    # EX Steper Motor Cal: steps/nm
    varEXstepsNm.set('50')
    #   "EMstepsNm:    50"    # EM Steper Motor Cal: steps/nm
    varEMstepsNm.set('50')    
    #
    # Now OVER-WRITE FACTORY with SITE'S SETTINGS
    try:
        tmpFile = open('settings.txt','r').read().splitlines()
        for line in tmpFile:
            #print('line = {}'.format(line))
            items = line.split()
            #
            # parse 'settings.txt' for 'default acquisition settings'
            # (DEFAULT ACQUISITION SETTINGS - last User Settings or Factory)
            #     EXinc:     1
            #     EMinc:     1
            #     TMinc:     0.1
            # (SITE ESTABLISHED SETTINGS)
            #     EXslit:    2.9
            #     EMslit:    2.9
            #     EMhv:     -900
            #     REFhv:    -450
            #     EXstepsNm: 10
            #     EMstepsNm: 10
            #
            if items[0] == "EXinc:":
                varEXinc.set(items[1])
            elif items[0] == "EMinc:":
                varEMinc.set(items[1])
            elif  items[0] == "TMinc:":
                varTMinc.set(items[1])
            elif items[0] == "EXslit:":
                varEXslit.set(items[1])
            elif items[0] == "EMslit:":
                varEMslit.set(items[1])
            elif items[0] == "EMhv:":
                varEMhv.set(items[1])
            elif items[0] == "REFdiode:":
                varREFdiodeG.set(items[1])
            elif items[0] == "REFhv:":
                varREFhv.set(items[1])
            elif items[0] == "EXstepsNm:":
                varEXstepsNm.set(items[1])
            elif items[0] == "EMstepsNm:":
                varEMstepsNm.set(items[1])
    except:
        pass    # no SITE SETTINGS WERE SAVED
        if jjltest:
            print('settings.txt does not exist!')
    #
    scanSanityCheck()   # verify ranges are 'reasonalbe' tint any not so
    return


#
## Settings Write (default settings, etc.) for measurement
def writeSettings():
    if jjltest:
        print('writeSettings()')
    # Write out Settings to 'settings.txt'
    fo = open('settings.txt','w')
    tempData  = [ '# user entered measurement settings'
                , 'EXinc: '  + varEXinc.get()
                , 'EMinc: '  + varEMinc.get()
                , 'TMinc: '  + varTMinc.get()
                , '# site established settings'
                , 'EXslit: ' + varEXslit.get()
                , 'EMslit: ' + varEMslit.get()
                , 'EMhv: '    + varEMhv.get()
                , 'REFdiode: ' + varREFdiodeG.get()
                , 'REFhv: '   + varREFhv.get()
                , '# site calibrated settings'
                , 'EXstepsNm: ' + varEXstepsNm.get()
                , 'EMstepsNm: ' + varEMstepsNm.get()
                ]
    #
    fo.write( '\n'.join(tempData) )
    fo.close()

#
## Settings Edit (default settings, etc.) for measurement
def editSettings():
    '''Edit 'settings.txt' to alter default values.'''
    #
    edset = Toplevel()
    edset.geometry(transGeom)
    edset.title("Spectrometer Settings")
    #
    #-------
    edsetTop = Frame(edset, bg = TANBG)
    edsetTop.grid()
    #
    # Site Established Settings - spectrometer setup
    #
    #     varEXslit   = StringVar()   # Setting EX Slit  Opening (nm)
    #     varEMslit   = StringVar()   # Setting EM Slit  Opening (nm)
    #     varEMhv         = StringVar()   # Setting EM PMT high voltage (v)
    #     varREFdiodeG    = StringVar()   # Setting for REF DIODE Gain 
    #     varREFhv        = StringVar()   # Setting REF PMT high voltage (v)
    #
    #
    # Site Established Settings - due to instrument setup.  I.E.
    # CALIBRATION SETTINGS - measured during calibration of spectrometer
    #       {stepper motor calibration values - should not need changing}
    #     varEXstepsNm = StringVar()   # EX StepMotor steps per (nm)
    #     varEMstepsNm = StringVar()   # EM StepMotor steps per (nm)
    #
    #-------
    edsetCf = LabelFrame(edsetTop, text="Site Established Settings." 
                        ,bg = TANBG, font=monoFont16
                        ,borderwidth=6)
    edsetCf.grid(row=1, padx=4, pady=4, sticky=EW)
    #
    # EX Slit size (nm)
    #-------
    EXiPL = Label(edsetCf, text = "EX Slit size (nm):"
               , bg = TANBG, font=monoFont14)
    EXiPL.grid(row=0, column=0, padx=4, sticky=W)
    #-------
    EXiPE = Entry(edsetCf, textvariable = varEXslit, font=monoFont14)
    EXiPE.grid(row=0, column=1, padx=4, sticky=E)
    #
    # EM Slit size (nm)
    #-------
    EMiPL = Label(edsetCf, text = "EM Slit size (nm):"
               , bg = TANBG, font=monoFont14)
    EMiPL.grid(row=1, column=0, padx=4, sticky=W)
    #-------
    EMiPE = Entry(edsetCf, textvariable = varEMslit, font=monoFont14)
    EMiPE.grid(row=1, column=1, padx=4, sticky=E)
    #
    # EM PMT high voltage (v)
    #-------
    EMhvL = Label(edsetCf, text = "EM PMT high voltage (v):"
               , bg = TANBG, font=monoFont14)
    EMhvL.grid(row=2, column=0, padx=4, sticky=W)
    #-------
    EMhvE = Entry(edsetCf, textvariable = varEMhv, font=monoFont14)
    EMhvE.grid(row=2, column=1, padx=4, sticky=E)
    #
    # REF DIODE Gain setting [0,1,2,3]
    #-------
    REFhvL = Label(edsetCf, text = "REF DIODE Gain Setting:"
               , bg = TANBG, font=monoFont14)
    REFhvL.grid(row=3, column=0, padx=4, sticky=W)
    #-------
    # varREFdiodeG    = StringVar()   # REF DIODE Gain setting [0,1,2,3]
    REFhvE = Entry(edsetCf, textvariable = varREFdiodeG, font=monoFont14)
    REFhvE.grid(row=3, column=1, padx=4, sticky=E)
    #
    # REF PMT high voltage (v)
    #-------
    REFhvL = Label(edsetCf, text = "REF PMT high voltage (v):"
               , bg = TANBG, font=monoFont14)
    REFhvL.grid(row=4, column=0, padx=4, sticky=W)
    #-------
    REFhvE = Entry(edsetCf, textvariable = varREFhv, font=monoFont14)
    REFhvE.grid(row=4, column=1, padx=4, sticky=E)
    #
    # EX Steper Motor Cal: steps/nm
    #-------
    EXnmCL = Label(edsetCf, text = "EX motor steps/nm:"
               , bg = TANBG, font=monoFont14)
    EXnmCL.grid(row=5, column=0, padx=4, sticky=W)
    #-------
    EXnmCE = Entry(edsetCf, textvariable = varEXstepsNm, font=monoFont14)
    EXnmCE.grid(row=5, column=1, padx=4, sticky=E)
    #
    # EM  Steper Motor Cal: steps/nm
    #-------
    EMnmCL = Label(edsetCf, text = "EM motor steps/nm:"
               , bg = TANBG, font=monoFont14)
    EMnmCL.grid(row=6, column=0, padx=4, sticky=W)
    #-------
    EMnmCE = Entry(edsetCf, textvariable = varEMstepsNm, font=monoFont14)
    EMnmCE.grid(row=6, column=1, padx=4, sticky=E)
    #
    #
    # editing DONE
    writeSettings()
    # next read in (apply) settings
    readSettings()
    # lastly Close Edit window
    edset.destroy()
    return  # ignore
    #
    bDone = Button(edsetTop, text = 'DONE', bg = TANBG, borderwidth=4 
                ,command = edsetDone
                ,activebackground=ACTIVB, font=monoFont16)
    bDone.grid(row=2,padx=4, pady=2, sticky=W)
    #
    edset.transient(siWin)
    edset.grab_set()
    siWin.wait_window(edset)
#     if jjltest:
#         print( 'editSettings(): Done!')
    return

#
## initialize hardware for RetroSPEX controller
#
def RetroSPEXinit():
    '''Load initial settings into controller.
    High Voltage = off (0 volts),
    Gain set to preset value,
    LED on front blink and then OFF,
    etc.'''
    #
    # purposely send command which generates 'e' (error) response
    # this clears out RetroSPEX's receive buffer and shows synchronization
    #
    crQappend( [ "*", "e", nop] )   # add to crQ for sending 
    #
    #TODO - HV setup
    print("#TODO - HV setup")
    #
    cmdD_HVoff()    # EMission and REFerence PMT voltage -> ZERO
    #
    #TODO - restore steppers (? or elsewhere ?)
    #TODO - begin 'real time data monitoring'
    print("#TODO - restore steppers (? or elsewhere ?)")
    print("#TODO - begin 'real time' data monitoring")
    return

#
## Calibration Input (odometer settings) for monochrometer
#
#     varLiveEXpos  = StringVar()    # EX monochrometer position (nm)
#     varLiveEMpos  = StringVar()    # EM monochrometer position (nm)
#
def monoCal():
    '''Get 'odometer' values for the monochrometers.
    (i.e. Calibrate SPEX monochrometers; EX and EM.)'''
    #
    cal = Toplevel()
    cal.geometry(transGeom)
    cal.title("Monochronometer Calibration")
    #
    calTop = Frame(cal, bg = TANBG)
    calTop.grid()
    #
    calf = LabelFrame(calTop, text="Verify odometer values." 
                     ,bg = TANBG, font=monoFont16
                     ,borderwidth=6)
    calf.grid(padx=4,pady=4)
    #
    lEX = Label(calf, text = "EXcitation:"
               , bg = TANBG, font=monoFont14)
    lEX.grid(row=0, column=0, padx=4, sticky=E)
    eEX = Entry(calf, textvariable = varLiveEXpos, font=monoFont14)
    eEX.grid(row=0, column=1, padx=4, sticky=E)
    def eEXchk(x=None):
        eEX['bg'] = 'white'
        return
    eEX.bind('<KeyRelease>',eEXchk)
    eEX.focus_set()
    #
    lEM = Label(calf, text = "EMission:"
               , bg = TANBG, font=monoFont14)
    lEM.grid(row=1, column=0, padx=4, sticky=E)
    eEM = Entry(calf, textvariable = varLiveEMpos, font=monoFont14)
    eEM.grid(row=1, column=1, padx=4, sticky=E)
    def eEMchk(x=None):
        eEM['bg'] = 'white'
        return
    eEM.bind('<KeyRelease>',eEMchk)
    #
    #
    def monoCheck(val, ent):
        '''True if val in 'legal' range, False otherwise.
        Sets Entry field pink when val is outside 'legal'.'''
        n = getVarInt(val)
        if n >= MINnm and n<= MAXnm:
            ent['bg'] = 'white'     # 'legal' value
            return True
        else:
            ent['bg'] = WARNC     # 'illegal' value
            ent.focus_set()
            return False
    #
    def monoCalDone(x=None):
        # Close window if both values are in 'normal' range
        if monoCheck(varLiveEXpos, eEX) and monoCheck(varLiveEMpos, eEM):
            writePositions()    # save Verified positions to file
            cal.destroy()
        return  # ignore
    #
    bDone = Button(calTop, text = 'DONE', bg = TANBG, borderwidth=4 
                ,command = monoCalDone
                ,activebackground=ACTIVB, font=monoFont16)
    bDone.grid(row=1, column=0, padx=4, pady=2, sticky=W)
    #
    cal.transient(siWin)
    cal.grab_set()
    siWin.wait_window(cal)
    print( '\nmonoCal(): done!')

    
#
## Power Up - operations to sequence initialization of hardware/software
#    
def PowerUp():
    '''Load "settings" and calibrate SPEX.'''  
    global serOutReady  
    #
    readSettings()      # load the Default settings for the spectrometer
    #
    # establish serial connection to RetroSPEX controller")
    # or, set to 'offline' mode to look at files, etc.")
    #
    portScan()      # search for serialPort to spectrometer
    #
    if portName != 'OFFLINE':
        #TODO flash LED repeatedly to indicate readyness
        print("TODO flash LED repeatedly to indicate readyness")
        cmdL_BlinkON()    # start 'blink-cycle' (low duty cycle default)
        #
        #TODO log "run time" (bulb life? - i.e. need start time)
        #
        #TODO if connected: Initialize RetroSPEX controller settings
        #TODO i.e. HV levels (0 volts initially), 'G'ain setting, etc.
        print("TODO: if connected: Initialize RetroSPEX controller settings")
        RetroSPEXinit()
        #
        print("TODO: if connected: Monochrometers by 10nm (anti-backlash)")
        readPositions()
        #TODO Move Monochrometers by -10nm/+10nm (anti-backlash)
        #
        # perform monochrometer calibration (verification)
        monoCal()
        #TODO ( => always move POS dir (or sept NEG val+10 and then POS 10)
        #TODO ( => real time display values initialize)
    #
    checkDayFile()
    #
    return
 

    
#
## Power Down - operations to sequence shutdown of hardware/software
#    
def PowerDown():    
    #
    if portName != 'OFFLINE':
        #
        #TODO stop scan if one is in process
        print("TODO: scan if one is in process")
        #
        #TODO if connected: ShutDown RetroSPEX controller settings
        #TODO i.e. HV levels => (0 volts), ... ??
        print("TODO: if connected: ShutDown RetroSPEX controller settings")
        #
        #TODO log "run time" (bulb life? - i.e. need start time)
    #
    #TODO log data such as monochrometer position on shutdown
    print("TODO: log data such as monochrometer position on shutdown")
    #
    return

#====================================
## Scan Control Frame
#
#-------
controlsFrame = Frame(siWin, bg = TANBG, borderwidth=0)
controlsFrame.grid(row=0,column=0, sticky=N)
#
#-------
scfScanControlFrame = LabelFrame(controlsFrame,text='Control', 
                bg = TANBG, borderwidth=4)
scfScanControlFrame.grid(row=0,column=0, sticky=N)
  
## Scan - START/STOP  -  Spectrometer scan control
#
scanStopIcon  = PhotoImage(file='icons/icon_scanSTOP.gif')
scanStartIcon  = PhotoImage(file='icons/icon_scanSTART.gif')
#
def scanStartStop():
    '''Scan Start/Stop  -  Spectrometer scan control'''
    global scannerState, STATEstop, STATEscan, STATEpause
    if scannerState != STATEstop:   # RUN or PAUSE => then STOP the scan !!
        if jjltest:
            print('STOPPING A SCAN IMPLEMENTED YET ;-)')
        setScannerState(STATEstop)
        runScfB00['image'] = scanStartIcon
    else:   # START up a scan
        # perform sanity checks before starting scan
        sane = scanSanityCheck( warn = True )
        if jjltest:
            print('STARTING A SCAN NOT IMPLEMENTED YET ;-)')
            sane = False
            #
            # PRETEND TO START SCANNING FOR TESTING
            setScannerState(STATEscan)
            runScfB00['image'] = scanStopIcon
        if sane:
            setScannerState(STATEscan)
            runScfB00['image'] = scanStopIcon
            #
            pass    # start scanning !
        else:
            pass    # DON"T  start scanning !
    return
#
#-------
runScfB00 = Button(scfScanControlFrame,image=scanStartIcon
                  ,borderwidth = 0,activebackground=ACTIVB
                  ,bg = TANBG, command = scanStartStop )
runScfB00.grid(column=0,row=0, padx=2)
  
## HV - On/Off  -  High Voltage  (red: safety concern)
#
hvOffIcon = PhotoImage(file='icons/icon_hvOff.gif')
hvOnIcon  = PhotoImage(file='icons/icon_hvOn.gif')
hvOn = False  # default == OFF
hvScfB01 = None     # forward reference to Button
#
def setHVon():
    '''HV - On -  High Voltage ON (red: safety concern)'''
    global hvOn, hvScfB01, hvOnIcon
    #
    if not hvOn:
        print('setHVon() HV OFF => ON')
        hvScfB01['image'] = hvOnIcon
        cmdD_HVon()     # turn HV on
        hvOn = True
    return
#
def setHVoff():
    '''HV - Off -  High Voltage OFF'''
    global hvOn, hvScfB01, hvOffIcon
    #
    if hvOn:
        print('setHVoff() HV ON => OFF')
        hvScfB01['image'] = hvOffIcon
        cmdD_HVoff()     # turn HV off
        hvOn = False
    return
#
def toggleHV():
    '''HV - On/Off  -  High Voltage  (red: safety concern)'''
    global hvOn
    #
    print('\nPushed "HV button"')
    if hvOn:
        setHVoff()     # turn HV off
    else:
        setHVon()      # turn HV on
    return
#
#-------
hvScfB01 = Button(scfScanControlFrame, image = hvOffIcon
                 ,activebackground=ACTIVB
                 ,borderwidth = 0, bg = TANBG, command = toggleHV)
hvScfB01.grid(column=0,row=1)

#====================================
## Ref. Data Frame  --  Load previous Scan Data for Reference or Settings recall
#
#-------
filesFrame = LabelFrame(controlsFrame,text='Ref. Data', 
                bg = TANBG, borderwidth=4)
filesFrame.grid(row=1,column=0, padx=2, sticky=NW)
#
#  LOAD experimental settings from disk
dataLoadIcon = PhotoImage(file='icons/icon_dataLOAD.gif')
#
#-------
fileFileDataLoad = Button(filesFrame, image=dataLoadIcon
                         , bg = TANBG, activebackground=ACTIVB
                         ,command = dataFileLOAD
                         ,borderwidth = 0, font=monoFont14 )
fileFileDataLoad.grid(row=0, column=0, sticky=NW)

#
#
dataMgetIcon = PhotoImage(file='icons/icon_dataMGET.gif')
#
#-------
fileSettingsGet = Button(filesFrame, image=dataMgetIcon, bg = TANBG 
                        ,command = dataFileMGET,activebackground=ACTIVB
                        ,borderwidth = 0, font=monoFont14 )
fileSettingsGet.grid(row=1, column=0,sticky=NW)
 



#====================================
## Macro Files Frame
#
#-------
macroFrame = LabelFrame(controlsFrame,text='Macro Files', 
                bg = TANBG, borderwidth=4)
macroFrame.grid(row=2,column=0, padx=2, sticky=NW)
#
#  LOAD scan settings from disk
macroLoadIcon = PhotoImage(file='icons/icon_macroLOAD.gif')
 
#
#-------
macroFileLoad = Button(macroFrame, image=macroLoadIcon, bg = TANBG
                      ,borderwidth = 0
                      ,activebackground=ACTIVB, font=monoFont14 )
macroFileLoad.grid(row=0, column=0,sticky=NW)

#
#
macroEditIcon = PhotoImage(file='icons/icon_macroEDIT.gif')
#
#-------
macroFileEdit = Button(macroFrame, image=macroEditIcon, bg = TANBG
                      , borderwidth = 0
                      ,activebackground=ACTIVB, font=monoFont14 )
macroFileEdit.grid(row=1, column=0,sticky=NW)
 
 



#====================================
## Settings Frame
#
#-------
settingsFrame = LabelFrame(controlsFrame,text='Settings', 
                bg = TANBG, borderwidth=4)
settingsFrame.grid(row=12,column=0, sticky=S)
#
#
settingsIcon = PhotoImage(file='icons/icon_settings.gif')
#
#-------
settingsBtn = Button(settingsFrame, image=settingsIcon, bg = TANBG
                    ,borderwidth = 0, command = editSettings
                    ,activebackground=ACTIVB, font=monoFont14 )
settingsBtn.grid()
 


#====================================
## Quit Frame
#
def quitCommand():
    #
    # Shutdown equipment
    #
    PowerDown()
    #
    siWin.destroy()
    
#-------
quitFrame = LabelFrame(controlsFrame,text='Quit', 
                bg = TANBG, borderwidth=4)
quitFrame.grid(row=13,column=0, sticky=S)
#
#
quitIcon = PhotoImage(file='icons/icon_quit.gif')
#
#-------
quitBtn = Button(quitFrame, image=quitIcon, bg = TANBG, borderwidth = 0
                ,command = quitCommand
                ,activebackground=ACTIVB, font=monoFont14 )
quitBtn.grid()




#====================================
## Experiment Frame  --  Window to right of Control frame
#
#-------
efFrame = Frame(siWin, bg = TANBG, borderwidth=0)
efFrame.grid(row=0,column=1,sticky=NW)


#====================================
## Experiment Settings Frame
#
#-------
esfFrame = Frame(efFrame, bg = TANBG, borderwidth=0)
esfFrame.grid(row=0,column=0,sticky=NW)

     

#====================================
## Spectrometer / Specimen Box Frame
#
#-------
ssbFrame = Frame(esfFrame, bg = TANBG, borderwidth=0)
ssbFrame.grid(row=0,column=0,sticky=EW)

#====================================
## Spectrometer Settings Frame
#
#-------
ssfFrame = LabelFrame(ssbFrame,text='Spectrometer Settings', 
            bg = TANBG, borderwidth=4)
ssfFrame.grid(row=0,column=0,sticky=NW)

#====================================
## Spectrometer EX Frame  -  EXcitation
#
#  EX scan
#
#-------
sEXfFrame = Frame(ssfFrame, bg = TANBG)
sEXfFrame.grid(row=0,column=0,sticky=NW)
#
#
sEXfB00_FR = NotImplemented    # forward reference to Button
sEMfB00_FR = NotImplemented    # forward reference to Button
sTMfB00_FR = NotImplemented    # forward reference to Button
#
exIconT = PhotoImage(file='icons/icon_modeEXt.gif')
exIconF = PhotoImage(file='icons/icon_modeEXf.gif')
#
emIconT = PhotoImage(file='icons/icon_modeEMt.gif')
emIconF = PhotoImage(file='icons/icon_modeEMf.gif')
#
tmIconT = PhotoImage(file='icons/icon_modeTMt.gif')
tmIconF = PhotoImage(file='icons/icon_modeTMf.gif')
#
def buttonEX():
    '''Display/Change scanning mode: to EXcitation.'''
    setScanMode(EXscan)
    return
#
#-------
sEXfB00 = Button(sEXfFrame, image = exIconT, bg = TANBG
                ,borderwidth=0, command = buttonEX,activebackground=ACTIVB)
sEXfB00.grid(row=0,column=0,sticky=W)
sEXfB00_FR = sEXfB00  # resolve the forward reference to this button

#
# Wavelength Setting (frame)
#-------
sEXwavFrame = Frame(sEXfFrame, bg = TANBG)
sEXwavFrame.grid(row=0,column=2,sticky=NW)
#
# Wavelength Start - Label
#-------
sEXwavSLabel = Label(sEXwavFrame, text='Start (nm)', font=monoFont12, bg = TANBG )
sEXwavSLabel.grid(row=0, column=0,padx=2,sticky=W)
#
# Wavelength End - Label
#-------
sEXwavELabel = Label(sEXwavFrame, text='End (nm)', font=monoFont12, bg = TANBG )
sEXwavELabel.grid(row=0, column=1,padx=2,sticky=W)
#
# Wavelength Inc - Label
#-------
sEXwavILabel = Label(sEXwavFrame, text='Inc (nm)', font=monoFont12, bg = TANBG )
sEXwavILabel.grid(row=0, column=2,padx=2,sticky=W)

#
#  Start wavelength  - Enter
#
def validateEXwaveStart(eventKeyRelease):
    sEXwavSEntry['bg'] = 'white'     # set button color 'white' on edit
    return
#
#-------
sEXwavSEntry = Entry(sEXwavFrame, textvariable=varEXwaveStart, 
          border=2, relief=SUNKEN, width=8, font=monoFont14 )
sEXwavSEntry.grid(row=1, column=0, padx=4, pady=2, sticky=W)
sEXwavSEntry.bind('<KeyRelease>',validateEXwaveStart)
#
btnLookup['EXS'] = sEXwavSEntry      # put button into dictionary by name
#
#  End wavelength  - Enter
#
def validateEXwaveEnd(eventKeyRelease):
    sEXwavEEntry['bg'] = 'white'     # set button color 'white' on edit
    return
#
#-------
sEXwavEEntry = Entry(sEXwavFrame, textvariable=varEXwaveEnd, 
          border=2, relief=SUNKEN, width=7, font=monoFont14 )
sEXwavEEntry.grid(row=1, column=1, padx=4, pady=2, sticky=W)
sEXwavEEntry.bind('<KeyRelease>',validateEXwaveEnd)
#
btnLookup['EXE'] = sEXwavEEntry      # put button into dictionary by name
#
#  Inc wavelength  - Enter
#
def validateEXwaveInc(eventKeyRelease):
    sEXwavIEntry['bg'] = 'white'     # set button color 'white' on edit
    return
#
#-------
sEXwavIEntry = Entry(sEXwavFrame, textvariable=varEXinc, 
          border=2, relief=SUNKEN, width=6, font=monoFont14 )
sEXwavIEntry.grid(row=1, column=2, padx=4, pady=2, sticky=W)
sEXwavIEntry.bind('<KeyRelease>',validateEXwaveInc)
#
btnLookup['EXI'] = sEXwavIEntry      # put button into dictionary by name

#====================================
## Spectrometer EM Frame  -  EMission
#
#  EM scan
#
#-------
sEMfFrame = Frame(ssfFrame, bg = TANBG)
sEMfFrame.grid(row=0,column=1,sticky=NW)
#
def buttonEM():
    '''Display/Change scanning mode: to EMission.'''
    setScanMode(EMscan)
    return
#
#-------
sEMfB00 = Button(sEMfFrame, image = emIconF, bg = TANBG
                ,borderwidth=0, activebackground=ACTIVB, command = buttonEM)
sEMfB00.grid(row=0,column=0,sticky=W)
sEMfB00_FR = sEMfB00  # resolve the forward reference to this button

#
# Wavelength Setting (frame)
#-------
sEMwavFrame = Frame(sEMfFrame, bg = TANBG)
sEMwavFrame.grid(row=0,column=2,sticky=NW)
#
# Wavelength Start - Label
#-------
sEMwavSLabel = Label(sEMwavFrame, text='Start (nm)', font=monoFont12, bg = TANBG )
sEMwavSLabel.grid(row=0, column=0,padx=2,sticky=W)
#
# Wavelength End - Label
#-------
sEMwavELabel = Label(sEMwavFrame, text='End (nm)', font=monoFont12, bg = TANBG )
sEMwavELabel.grid(row=0, column=1,padx=2,sticky=W)
#
# Wavelength Inc - Label
#-------
sEMwavILabel = Label(sEMwavFrame, text='Inc (nm)', font=monoFont12, bg = TANBG )
sEMwavILabel.grid(row=0, column=2,padx=2,sticky=W)

#
#  Start wavelength  - Enter
#
def validateEMwaveStart(eventKeyRelease):
    sEMwavSEntry['bg'] = 'white'     # set button color 'white' on edit
    return
#
#-------
sEMwavSEntry = Entry(sEMwavFrame, textvariable=varEMwaveStart, 
          border=2, relief=SUNKEN, width=8, font=monoFont14 )
sEMwavSEntry.grid(row=1, column=0, padx=4, pady=2, sticky=E)
sEMwavSEntry.bind('<KeyRelease>',validateEMwaveStart)
#
btnLookup['EMS'] = sEMwavSEntry      # put button into dictionary by name

#
#  End wavelength  - Enter
#
def validateEMwaveEnd(eventKeyRelease):
    sEMwavEEntry['bg'] = 'white'     # set button color 'white' on edit
    return
#
#-------
sEMwavEEntry = Entry(sEMwavFrame, textvariable=varEMwaveEnd, 
          border=2, relief=SUNKEN, width=7, font=monoFont14 )
sEMwavEEntry.grid(row=1, column=1, padx=4, pady=2, sticky=EW)
sEMwavEEntry.bind('<KeyRelease>',validateEMwaveEnd)
#
btnLookup['EME'] = sEMwavEEntry      # put button into dictionary by name

#
#  Inc wavelength  - Enter
#
def validateEMwaveInc(eventKeyRelease):
    sEMwavIEntry['bg'] = 'white'     # set button color 'white' on edit
    return
#
#-------
sEMwavIEntry = Entry(sEMwavFrame, textvariable=varEMinc, 
          border=2, relief=SUNKEN, width=6, font=monoFont14 )
sEMwavIEntry.grid(row=1, column=2, padx=4, pady=2, sticky=EW)
sEMwavIEntry.bind('<KeyRelease>',validateEMwaveInc)
#
btnLookup['EMI'] = sEMwavIEntry      # put button into dictionary by name

#====================================
## Spectrometer TM Frame  -  TiMe
#
#  TM scan
#
#-------
sTMfFrame = Frame(ssfFrame, bg = TANBG)
sTMfFrame.grid(row=0,column=2,sticky=NW)
#
def buttonTM():
    '''Display/Change scanning mode: to EXcitation.'''
    setScanMode(TMscan)
    return
#
#-------
sTMfB00 = Button(sTMfFrame, image = tmIconF, bg = TANBG,
                borderwidth=0,activebackground=ACTIVB, command = buttonTM)
sTMfB00.grid(row=0,column=0,sticky=W)
sTMfB00_FR = sTMfB00  # resolve the forward reference to this button
#
#
# Time Setting (frame)
#-------
sTMwavFrame = Frame(sTMfFrame, bg = TANBG)
sTMwavFrame.grid(row=0,column=1,sticky=NW)
#
# Pause step# - Label
#-------
sTMwavPLabel = Label(sTMwavFrame, text='Pause(S)'
                    , font=monoFont12, bg = TANBG )
sTMwavPLabel.grid(row=0, column=0,padx=2,sticky=W)
#
# End step# - Label
#-------
sTMwavELabel = Label(sTMwavFrame, text='End (S)'
                , font=monoFont12, bg = TANBG )
sTMwavELabel.grid(row=0, column=1,padx=2,sticky=W)
#
# Increment Time - Label
#-------
sTMwavILabel = Label(sTMwavFrame, text='Inc (S)'
                    , font=monoFont12, bg = TANBG )
sTMwavILabel.grid(row=0, column=2,padx=2,sticky=W)
# 
#
#  Pause (step#)  - Enter
#
def validateTMwavePause(eventKeyRelease):
    sTMwavPEntry['bg'] = 'white'     # set button color 'white' on edit
    return
#
#-------
sTMwavPEntry = Entry(sTMwavFrame, textvariable=varTMwavePause, 
          border=2, relief=SUNKEN, width=6, font=monoFont14 )
sTMwavPEntry.grid(row=1, column=0, padx=4, pady=2, sticky=EW)
sTMwavPEntry.bind('<KeyRelease>',validateTMwavePause)
#
btnLookup['TMP'] = sTMwavPEntry      # put button into dictionary by name

#
#  End step#  - Enter
#
def validateTMwaveEnd(eventKeyRelease):
    sTMwavEEntry['bg'] = 'white'     # set button color 'white' on edit
    return
#
#-------
sTMwavEEntry = Entry(sTMwavFrame, textvariable=varTMwaveEnd, 
          border=2, relief=SUNKEN, width=6, font=monoFont14 )
sTMwavEEntry.grid(row=1, column=1, padx=4, pady=2, sticky=EW)
sTMwavEEntry.bind('<KeyRelease>',validateTMwaveEnd)
#
btnLookup['TME'] = sTMwavEEntry      # put button into dictionary by name

#
#  Increment Time  - Enter
#
def validateTMwaveInc(eventKeyRelease):
    sTMwavIEntry['bg'] = 'white'     # set button color 'white' on edit
    return
#
#-------
sTMwavIEntry = Entry(sTMwavFrame, textvariable=varTMinc, 
          border=2, relief=SUNKEN, width=6, font=monoFont14 )
sTMwavIEntry.grid(row=1, column=2, padx=4, pady=2, sticky=W)
sTMwavIEntry.bind('<KeyRelease>',validateTMwaveInc)
#
btnLookup['TMI'] = sTMwavIEntry      # put button into dictionary by name


#====================================
## S+R Frame  -  record Reference data?
#
#  S+R 
#
#-------
srFrame = Frame(ssfFrame, bg = TANBG)
srFrame.grid(row=0,column=3,sticky=NW)
#  
# Reference Data - On/Off - 'S'(signal) alone or with 'R'(reference) too?
#
refOffIcon = PhotoImage(file='icons/icon_refOff.gif')
refOnIcon  = PhotoImage(file='icons/icon_refOn.gif')
refOn = False  # default == OFF (i.e. 'S' and 'R')
#
def toggleRef():
    '''Ref - On/Off - 'S'(signal) alone or with 'R'(reference) too?'''
    global refOn
    refOn = toggleBtnVar(refOn, refScfB02, refOffIcon, refOnIcon)
    return
#
#-------
refScfB02 = Button(srFrame, image = refOffIcon, borderwidth = 0
                  ,bg = TANBG,activebackground=ACTIVB, command = toggleRef)
refScfB02.grid(row=0,column=0,sticky=W)


#====================================
## Set 'scan mode'  -  complete forward reference
#
def setScanMode(mode):
    '''Select the type of spectrometer scan to perform.
    Sets the EX, EM and TM Icons to incidate scan type.
    Sets the 'state' (NORMAL/DISABLE) for scan setting params.'''
    #
    # any change?
    if varScanMode.get() == mode:
        if jjltest:
            print('setScanMode(): NO change.')
        return  # no change
    #
    varScanMode.set(mode)   # set the scan mode
    #
    # update icons
    if varScanMode.get() == EXscan :
        sEXfB00_FR['image'] = exIconT # SCAN MODE - back to Default
        sEMfB00_FR['image'] = emIconF
        sTMfB00_FR['image'] = tmIconF
    elif varScanMode.get() == EMscan :
        sEXfB00_FR['image'] = exIconF
        sEMfB00_FR['image'] = emIconT # SCAN MODE
        sTMfB00_FR['image'] = tmIconF
    elif varScanMode.get() == TMscan :
        sEXfB00_FR['image'] = exIconF
        sEMfB00_FR['image'] = emIconF
        sTMfB00_FR['image'] = tmIconT # SCAN MODE
    else:
        if jjltest:
            print('Bad scan mode found in setScanMode(mode)')
        sys.exit(0)
    #
    updatePlot()            # synchronize plot with scan mode
    #
    # set the correct 'state' for wavelength/time icons
    #
    if varScanMode.get() == EXscan:
        sEXwavSLabel['text']  = 'Start (nm)' # EXscan - Start wavelength
        sEXwavELabel['text']  = 'End (nm)'   #        - End   label set
        sEXwavEEntry['state'] = NORMAL     #        - End   entry enabled
        sEXwavILabel['text']  = 'Inc (nm)'   #        - Inc   label set
        sEXwavIEntry['state'] = NORMAL     #        - Inc   entry enabled
        sEMwavSLabel['text']  = 'Park (nm)' # EMscan - EM wavelength Parked
        sEMwavELabel['text']  = ''         #        - End   label cleared
        sEMwavEEntry['state'] = DISABLED   #        - End   entry disabled
        sEMwavILabel['text']  = ''         #        - Inc   label cleared
        sEMwavIEntry['state'] = DISABLED   #        - Inc   entry disabled
        sTMwavPLabel['text']  = ''         # TMscam - Pause label cleared
        sTMwavPEntry['state'] = DISABLED   #        - Pause entry disabled
        sTMwavELabel['text']  = ''         #        - End label cleared
        sTMwavEEntry['state'] = DISABLED   #        - End entry disabled
    elif varScanMode.get() == EMscan:
        sEXwavSLabel['text']  = 'Park (nm)' # EXscan - EX wavelength Parked
        sEXwavELabel['text']  = ''         #        - End   label cleared
        sEXwavEEntry['state'] = DISABLED   #        - End   entry disabled
        sEXwavILabel['text']  = ''         #        - Inc   label cleared
        sEXwavIEntry['state'] = DISABLED   #        - End   entry disabled
        sEMwavSLabel['text']  = 'Start (nm)' # EMscan - EM wavelength set
        sEMwavELabel['text']  = 'End (nm)'   #        - End   label set
        sEMwavEEntry['state'] = NORMAL     #        - End   entry  enabled
        sEMwavILabel['text']  = 'Inc (nm)'   #        - Inc   label set
        sEMwavIEntry['state'] = NORMAL     #        - Inc   entry  enabled
        sTMwavPLabel['text']  = ''         # TMscam - Pause label cleared
        sTMwavPEntry['state'] = DISABLED   #        - Pause entry disabled
        sTMwavELabel['text']  = ''         #        - End label cleared
        sTMwavEEntry['state'] = DISABLED   #        - End entry disabled
    elif varScanMode.get() == TMscan:
        sEXwavSLabel['text']  = 'Park (nm)' # EXscan - EX wavelength Parked
        sEXwavELabel['text']  = ''         #        - End   label cleared
        sEXwavEEntry['state'] = DISABLED   #        - End   entry disabled 
        sEXwavILabel['text']  = ''         #        - Inc   label cleared
        sEXwavIEntry['state'] = DISABLED   #        - End   entry disabled
        sEMwavSLabel['text']  = 'Park (nm)' # EMscan - EM wavelength Parked
        sEMwavELabel['text']  = ''         #        - End   label cleared
        sEMwavEEntry['state'] = DISABLED   #        - End   entry disabled
        sEMwavILabel['text']  = ''         #        - Inc   label cleared
        sEMwavIEntry['state'] = DISABLED   #        - Inc   entry disabled
        sTMwavPLabel['text']  = 'Pause(S)' # TMscam - Pause label set
        sTMwavPEntry['state'] = NORMAL     #        - Pause entry  enabled
        sTMwavELabel['text']  = 'End (S)'  #        - End label set
        sTMwavEEntry['state'] = NORMAL     #        - End entry enabled
    else:
        err = 'Internal Errr: undefined scan mode: {} !'
        mBox.showerror(title='Fatal Error'
                      ,message=err.format(varScanMode.get()))
        sys.exit(0)
    #
    scanSanityCheck()       # update out-of-bounds parameter coloring
    return
#    
setScanMode_FR = setScanMode        # resolve the Forward Reference to function


#====================================
## Specimen Details Frame
#
#-------
sdFrame = LabelFrame(ssbFrame,text='Specimen Details', bg = TANBG, borderwidth=0)
sdFrame.grid(row=1,column=0, pady=4, sticky=NW)

sdEntry = Entry(sdFrame, textvariable=varSpecimenDetails , 
            width=96, bg = 'white', border=2, relief=SUNKEN, font=monoFont14)
sdEntry.grid(row=0, column=0, padx=20, pady=2, sticky=EW)
sdEntry.bind('<KeyRelease>',updatePlot)


#====================================
## Real Time data Frame  -- frame inside Experiment Frame
#
#  Frame to hold real time data
#-------
rtdmFrame = LabelFrame(esfFrame, text='Live Data', bg = TANBG, borderwidth=4)
rtdmFrame.grid(row=0,column=1, padx=4, pady=2,sticky=NS+E)
#
#
# Real Time Data -- Row 0 => Signal
#-------
rtdmLabel00 = Label(rtdmFrame, text='S:', font=monoFont14, bg = TANBG )
rtdmLabel00.grid(row=0, column=0,sticky=E)
#-------
rtdmLabel00 = Label(rtdmFrame, textvariable=varLiveSignal
                   ,border=0, relief=FLAT, bg='white'
                   ,width=15, font=monoFont12, anchor=E )
rtdmLabel00.grid(row=0, column=1, padx=4, pady=2, sticky=W)
#
# Real Time Data -- Row 1 => Reference
#-------
rtdmLabel10 = Label(rtdmFrame, text='R:', font=monoFont14, bg = TANBG )
rtdmLabel10.grid(row=1, column=0,sticky=E)
#-------
rtdmLabel11 = Label(rtdmFrame, textvariable=varLiveReference
                   ,border=0, relief=FLAT, bg='white'
                   ,width=15, font=monoFont12, anchor=E )
rtdmLabel11.grid(row=1, column=1, padx=4, pady=2, sticky=W)
#
# Real Time Data -- Row 2 => PCT (%) scan complete
#-------
rtdmLabel40 = Label(rtdmFrame, text='%:', font=monoFont14, bg = TANBG )
rtdmLabel40.grid(row=2, column=0,sticky=E)

rtdmProgress41 = Progressbar(rtdmFrame, orient='horizontal'
                            ,mode='determinate', variable=varPCTdone
                            ,length=124)
rtdmProgress41.grid(row=2, column=1, padx=4, pady=2,sticky=W)
#
#
# FRAME for Real Time Data2 -- EX/EM position and HV readings
#
rtdmFrame2 = Frame(rtdmFrame, bg = TANBG)
rtdmFrame2.grid(row=3,columnspan=2, padx=0, pady=0,sticky=NSEW)
#
# Real Time Data2 -- Row 0,[Col 0&1] => EX monochrometer position (nm)
#-------
rtdm2Label00 = Label(rtdmFrame2, text='EX:', font=monoFont14, bg = TANBG )
rtdm2Label00.grid(row=0, column=0,sticky=E)
#-------
rtdm2Label01 = Label(rtdmFrame2, textvariable=varLiveEXpos
                   ,border=0, relief=FLAT, bg='white'
                   ,width=4, font=monoFont12, anchor=E )
rtdm2Label01.grid(row=0, column=1, padx=2, pady=2, sticky=W)
#
# Real Time Data -- Row 0,[Col 2&3] => EM monochrometer position (nm)
#-------
rtdm2Label02 = Label(rtdmFrame2, text='EM:', font=monoFont14, bg = TANBG )
rtdm2Label02.grid(row=0, column=2,sticky=E)
#-------
rtdm2Label03 = Label(rtdmFrame2, textvariable=varLiveEMpos
                   ,border=0, relief=FLAT, bg='white'
                   ,width=4, font=monoFont12, anchor=E )
rtdm2Label03.grid(row=0, column=3, padx=2, pady=2, sticky=W)
#
# Real Time Data2 -- Row 1,[Col 0&1] => EM PMT HV readings (v)
#-------
rtdm2Label10 = Label(rtdmFrame2, text='HVm:', font=monoFont14, bg = TANBG )
rtdm2Label10.grid(row=1, column=0,sticky=E)
#-------
rtdm2Label11 = Label(rtdmFrame2, textvariable=varLiveEMhv
                   ,border=0, relief=FLAT, bg='white'
                   ,width=4, font=monoFont12, anchor=E )
rtdm2Label11.grid(row=1, column=1, padx=2, pady=2, sticky=W)
#
# Real Time Data -- Row 1,[Col 2&3] => REF PMT HV readings (v)
#-------
rtdm2Label22 = Label(rtdmFrame2, text='HVr:', font=monoFont14, bg = TANBG )
rtdm2Label22.grid(row=1, column=2,sticky=E)
#-------
rtdm2Label23 = Label(rtdmFrame2, textvariable=varLiveREFhv
                   ,border=0, relief=FLAT, bg='white'
                   ,width=4, font=monoFont12, anchor=E )
rtdm2Label23.grid(row=1, column=3, padx=2, pady=2, sticky=W)

#====================================
## Plotting Frame
#
#-------
plotFrame = Frame(efFrame, bg = TANBG, borderwidth=0)
plotFrame.grid(row=2,column=0, sticky=NSEW)

#
fig = Figure(figsize = (11.56,6), dpi=100)   # TopLevel container for all plot elements
#
# initialize the "plot" element as "ax"
#
ax = fig.add_subplot(111, axisbg='w')   
#
canvas = FigureCanvasTkAgg(fig, master=plotFrame)
canvas.get_tk_widget().grid(row=0,column=0, padx=2)
#
def updatePlot():
    global ax
    global scanDataX,scanDataY
    global backgroundDataX,backgroundDataY
#     #
#     # returns Axes instance for single plot
#     try:
#         fig.axes.remove(ax)
#     except:
#         pass

    #print('CALLED: updatePlot()  len(scanDataX)={}'.format(len(scanDataX)))
    #
    # remove 'old' lines before re-draw
    while len(ax.lines):
        ax.lines.remove(ax.lines[-1])
    #
    # Get correct scaling for X axis
    #
    minX = 200
    maxX = 1000
    sm = varScanMode.get()
    if sm == EXscan:
        if jjltest:
            print('Error: EXscan not implemented.')
        else:
            mBox.showerror(message='Error: EXscan not implemented.')
        startX = minX
        endX = maxX
    elif sm == EMscan:
        if getVarInt(varEMwaveEnd) - getVarInt(varEMwaveStart) < 2:
            startX = minX
            endX   = maxX
        else:
            startX = getVarInt(varEMwaveStart)
            endX = getVarInt(varEMwaveEnd)
    elif sm == TMscan:
        if jjltest:
            print('Error: TMscan not implemented.')
        else:
            mBox.showerror(message='Error: TMscan not implemented.')
        startX = minX
        endX = maxX
    else:
        mErr('Error: updatePlot() invalid varScanMode')
        sys.exit(0)
    #
    # Get correct scaling for Y axis
    #
    if len(scanDataY) <  2 :
        maxScanY = 5000     # default if NO scan data
    else:
        maxScanY = 1.1*max(scanDataY)
    #
    if len(backgroundDataY) <  2 :
        maxInputY = 5000     # default if NO input (reference) data
    else:
        maxInputY = 1.1*max(backgroundDataY)
    #
    maxY = max(5000, maxScanY, maxInputY)
    #
    # set the X & Y sizes for axes now
    #
    ax.axis([startX, endX, 0, maxY ])
    #
    setPlotTitle()
    ax.set_ylabel('counts')
    #
    # plot "background" waveform (IF one has been loaded)
    if len(backgroundDataX) > 1:
#         if jjltest:
#             print('\nbefore: len(ax.lines)={}'.format(len(ax.lines)))
#         #ax.plot(scanDataX, scanDataY, 'b')
#         if jjltest:
#             print('mid: len(ax.lines)={}'.format(len(ax.lines)))
        ax.plot(backgroundDataX, backgroundDataY, 'g')
#         if jjltest:
#             print('after: len(ax.lines)={}'.format(len(ax.lines)))
#         if jjltest:
#             txt_ = 'len(backgroundDataX):{}, len(backgroundDataY):{}'
#             print(txt_.format(len(backgroundDataX),len(backgroundDataY)))
    #
    #  xlabel depends upon type of scan:  (varScanMode)
    #       EXscan = 0, EMscan = 1, TMscan = 2; 
    #
    if varScanMode.get() == TMscan:
        ax.set_xlabel('time (S)')          # scan by time
    else:
        ax.set_xlabel('wavelength (nm)')    # scan by wavelength
    #
    # set up "cursor" to display values from plot
    #
    cursor = Cursor(ax, horizOn=False, useblit=True, color='red', linewidth=2 )
    #cursor = Cursor(ax, horizOn=False,  color='red', linewidth=2 )
    #
    canvas.show()
#
updatePlot_FR = updatePlot  # resolve the Forward Reference to updatePlot()
# ========================




#=================
## Start up Window
#
setScanMode(EMscan)     # establish default EX scan type
updatePlot()            # draw the graph
#
PowerUp()               # initialize settings & calibrate SPEX
#
siWin.mainloop()

