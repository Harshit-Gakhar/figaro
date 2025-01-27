"""Handles the interactive shell for the user"""

import os, pyaudio, wave, shutil, numpy as np, time, re, importlib.util, json as JSON
import pash.shell, pash.cmds, pash.command as pcmd, colorama as cr
cr.init()
from asciimatics.screen import Screen
from typing import List

from figaro import params, utils, server, gui, filters
from figaro.sound import Sound
from figaro.device import Device
from figaro.channel import Channel
from figaro.interpreter import Interpreter
from figaro.filters.filter import Filter
from figaro.server import db
from figaro.server.models.user import User

"""The basic prompt for the figaro shell"""
BPROMPT: str = cr.Fore.LIGHTBLUE_EX + 'figaro' + cr.Fore.LIGHTBLACK_EX + '$ ' + cr.Fore.RESET
"""The shell itself"""
sh: pash.shell.Shell = pash.shell.Shell(prompt=BPROMPT)
"""The main PyAudio object"""
pa: pyaudio.PyAudio = pyaudio.PyAudio()
"""The main audio channel"""
ch: Channel = Channel()
"""A list of all running interpreters"""
interpreters: List[Interpreter] = []

def on_exit(cmd: pcmd.Command, args: List[str]) -> None:
    """Callback for `exit` - quits the shell"""
    if ch.is_alive():
        ch.kill()
    ch.kill_all()
    pa.terminate()
    gui.stop()
    sh.exit()

def on_show_devices(cmd: pcmd.Command, args: List[str], json: bool) -> None:
    """Callback for `show devices` - lists all audio devices"""
    devs = [pa.get_device_info_by_host_api_device_index(0, i) for i in range(pa.get_host_api_info_by_index(0).get('deviceCount'))]
    fil_d = lambda s: [(i, d['name']) for i, d in enumerate(devs) if d[s] > 0]
    if not json:
        print('Devices:\n ', end='')
        print('\r Input:\n   ', end='')
        print('\n   '.join(['{:02d}: {}'.format(*inf) for inf in fil_d('maxInputChannels')]))
        print('\r Output:\n   ', end='')
        print('\n   '.join(['{:02d}: {}'.format(*inf) for inf in fil_d('maxOutputChannels')]))
        return
    print(JSON.dumps({
        'input': fil_d('maxInputChannels'),
        'output': fil_d('maxOutputChannels'),
    }))

def on_show_status(cmd: pcmd.Command, args: List[str], json: bool) -> None:
    """Callback for `show status` - shows the audio channel's status"""
    if not json:
        print(ch)
        return
    print(JSON.dumps({
        'input': list(map(lambda d: d.toJSON(), ch.get_ists())),
        'output': list(map(lambda d: d.toJSON(), ch.get_osts())),
        'running': ch.is_running(),
    }))

def on_show_audio(cmd: pcmd.Command, args: List[str], scale: float, char: str) -> None:
    """Callback for `show audio` - shows the detected input"""
    if not ch.is_alive():
        utils.printerr('The audio channel isn\'t running at the moment ... ')
        return
    w, h = shutil.get_terminal_size()
    bw, bh = w//4*3, h
    def disp_audio(screen: Screen) -> None:
        while True:
            screen.clear()
            b = ch.buff
            sw = len(b)//bw
            b = np.asarray([np.average(b[i:i+sw]) for i in range(0, len(b), sw)])
            for i, v in enumerate(b):
                screen.move((w-bw)//2+i, int(h//2-bh*v*scale))
                screen.draw((w-bw)//2+i, h//2, char=char, colour=1 if np.max(b) > .2 else 7)
            e = screen.get_key()
            if e in (ord('Q'), ord('q')):
                break
            screen.refresh()
            time.sleep(.01)
    Screen.wrapper(disp_audio)

def on_show_sounds(cmd: pcmd.Command, args: List[str], json: bool) -> None:
    """Callback for `show sounds` - shows all currently playing sounds"""
    if not ch.sounds:
        if not json:
            utils.printwrn('No sounds are playing at the moment ... ')
        else:
            print(JSON.dumps({ 'error': 'No sounds are playing at the moment ... '}))
        return
    if not json:
        print('Sounds: ')
        for i, s in enumerate(ch.get_sounds()):
            print(' #{:02d} | {}'.format(i, str(s)))
        return
    print(JSON.dumps({
        'sounds': list(map(lambda s: s.toJSON(), ch.get_sounds())),
    }))

def on_show_all_sounds(cmd: pcmd.Command, args: List[str], json: bool) -> None:
    """Callback for `show sounds all` - shows all available sounds"""
    spath = os.path.join(params.BPATH, 'res', 'sounds')
    if not os.path.isdir(spath):
        if not json:
            utils.printerr(f'Directory "{spath}" doesn\'t exist ... ')
        else:
            print(JSON.dumps({ 'error': f'Directory "{spath}" doesn\'t exist ... '}))
        return
    sounds = [s for s in os.listdir(spath) if os.path.isfile(os.path.join(spath, s)) and s.split('.')[-1] in params.ALLOWED_EXTS]
    if not sounds:
        if not json:
            utils.printwrn('No sounds available ... ')
        else:
            print(JSON.dumps({ 'error': 'No sounds available ... '}))
        return
    if not json:
        print('Available sounds:\n - ', end='')
        print('\n - '.join(sounds))
        return
    print(JSON.dumps({
        'sounds': sounds,
    }))

def on_show_interpreters(cmd: pcmd.Command, args: List[str]) -> None:
    """Callback for `show interpreters` - shows all running interpreters"""
    if not interpreters:
        utils.printwrn('No interpreters running ... ')
        return
    print('Interpreters: ')
    for i, p in enumerate(interpreters):
        print(' #{:02d} | {}'.format(i, str(p)))

def on_show_running_filters(cmd: pcmd.Command, args: List[str], json: bool) -> None:
    """Callback for `show filters` - shows all running voice-filters"""
    filters = ch.get_filters()
    if not filters:
        if not json:
            utils.printwrn('No filters running ... ')
        else:
            print(JSON.dumps({ 'error': 'No filters running ... ', }))
        return
    if not json:
        print('Filters: ')
        for i, f in enumerate(filters):
            print(f' #{i:02d} | {f}')
        return
    print(JSON.dumps({
        'filters': list(map(lambda f: f.toJSON(), filters)),
    }))

def on_show_all_filters(cmd: pcmd.Command, args: List[str], json: bool) -> None:
    """Callback for `show filters all` - shows all available voice-filters"""
    filters.manager.collectPlugins()
    plugins = filters.get_names()
    if not plugins:
        if not json:
            utils.printwrn('No filters available ... ')
        else:
            print(JSON.dumps({ 'error': 'No filters available ... ', }))
        return
    if not json:
        print('Filters: \n - ', end='')
        print('\n - '.join(plugins))
        return
    print(JSON.dumps({
        'filters': [{
            'name': p,
            'html': filters.get(p).plugin_object.html().strip(),
        } for p in plugins],
    }))

def on_start_sound(cmd: pcmd.Command, args: List[str], parameters: List[str], json: bool) -> None:
    """Callback for `start sound` - adds a sound effect"""
    for i, a in enumerate(parameters):
        if re.match(r'^[\d\.]*$', a):
            continue
        if not os.path.isfile(a):
            a = os.path.join(params.BPATH, 'res', 'sounds', a)
        if not os.path.isfile(a):
            if not json:
                utils.printerr(f'File "{a}" doesn\'t exist ... ')
                continue
            else:
                print(JSON.dumps({ 'error': f'File "{a}" doesn\'t exist ... "', }))
                return
        try:
            if i+1 < len(args) and re.match(r'^[\d\.]+$', args[i+1]):
                ch.add_sound(Sound(a, float(args[i+1])))
                continue
            ch.add_sound(Sound(a))
        except Exception as e:
            if not json:
                utils.printerr(str(e))
            else:
                print(JSON.dumps({ 'error': str(e), }))
        if json:
            print(JSON.dumps({}))

def on_start_output(cmd: pcmd.Command, args: List[str], indo: int, json: bool) -> None:
    """Callback for `start output` - adds an output device"""
    try:
        ch.add_ost(Device(pa, format=pyaudio.paFloat32, channels=1, rate=params.SMPRATE, output=True, output_device_index=indo))
        if json:
            print(JSON.dumps({}))
    except Exception as e:
        if not json:
            utils.printerr(str(e))
        else:
            print(JSON.dumps({ 'error': str(e), }))

def on_start_input(cmd: pcmd.Command, args: List[str], indi: int, json: bool) -> None:
    """Callback for `start input` - adds an input device"""
    try:
        ch.add_ist(Device(pa, format=pyaudio.paFloat32, channels=1, rate=params.SMPRATE, input=True, input_device_index=indi))
        if json:
            print(JSON.dumps({}))
    except Exception as e:
        if not json:
            utils.printerr(str(e))
        else:
            print(JSON.dumps({ 'error': str(e), }))

def on_start_interpreter(cmd: pcmd.Command, args: List[str], fname: str) -> None:
    """Callback for `start interpreter` - interprets a .fig file"""
    try:
        interpreters.append(Interpreter(fname, ch, sh))
        interpreters[-1].exec()
    except Exception as e:
        utils.printerr(str(e))

def on_start_filter(cmd: pcmd.Command, args: List[str], name: str, cargs: List[str]) -> None:
    """Callback for `start interpreter` - interprets a .fig file"""
    name = name.lower()
    plugins = filters.get_names()
    if name not in map(lambda p: p.lower(), plugins):
        utils.printerr(f'Error: Unknown filter "{name}" ... ')
        return
    p = filters.get(plugins[[p.lower() for p in plugins].index(name)])
    try:
        ch.add_filter(p.plugin_object.start(cargs))
    except NameError as e:
        utils.printerr('Error: Invalid/incomplete filter definition ... ')
        utils.printerr(str(e))
    except Exception as e:
        utils.printerr('Error: Filter init error ... ')
        utils.printerr(str(e))

def on_start_server(cmd: pcmd.Command, args: List[str]) -> None:
    """Callback for `start server` - starts the websocket server"""
    if not os.path.isfile(params.DB_PATH):
        db.setup()
        print('== SETUP ' + '='*(shutil.get_terminal_size().columns-len('== SETUP ')-1))
        User.create_prompt()
        pash.cmds.clear(None, [])
        print('== SETUP ' + '='*(shutil.get_terminal_size().columns-len('== SETUP ')-1))
        server.create_conf_prompt()
    server.start(sh, ch)

def on_stop_sound(cmd: pcmd.Command, args: List[str], ind: str, json: bool) -> None:
    """Callback for `stop sound` - removes a sound effect"""
    if ind.lower() in ('a', 'all'):
        ch.del_all_sounds()
    else:
        try:
            ind = int(ind)
        except ValueError:
            if not json:
                utils.printerr(f'"{ind} is not a valid index!')
            else:
                print(JSON.dumps({ 'error': f'"{ind} is not a valid index!' }))
            return
        mxind = len(ch.get_sounds())-1
        if ind > mxind:
            if not json:
                utils.printerr(f'Index {ind} is out of bounds (max: {mxind})!')
            else:
                print(JSON.dumps({ 'error': f'Index {ind} is out of bounds (max: {mxind})!' }))
            return
        ch.del_sound(ind)
    if json:
        print(JSON.dumps({}))

def on_stop_output(cmd: pcmd.Command, args: List[str], indo: int, json: bool) -> None:
    """Callback for `stop output` - removes an output device"""
    if not indo in [d.indo for d in ch.get_osts()]:
        if not json:
            utils.printwrn('Device isn\'t currently being used ... ')
        else:
            print(JSON.dumps({ 'error': 'Device isn\'t currently being used ... ', }))
        return
    ch.del_ost(indo)
    if json:
        print(JSON.dumps({}))

def on_stop_input(cmd: pcmd.Command, args: List[str], indi: int, json: bool) -> None:
    """Callback for `stop input` - removes an input device"""
    if not indi in [d.indi for d in ch.get_ists()]:
        if not json:
            utils.printwrn('Device isn\'t currently being used ... ')
        else:
            print(JSON.dumps({ 'error': 'Device isn\'t currently being used ... ', }))
        return
    ch.del_ist(indi)
    if json:
        print(JSON.dumps({}))

def on_stop_interpreter(cmd: pcmd.Command, args: List[str], ind: str) -> None:
    """Callback for `stop interpreter` - stops a running interpreter"""
    global interpreters
    if ind.lower() in ('a', 'all'):
        for i in interpreters:
            i.kill()
        interpreters = []
        return
    try:
        ind = int(ind)
    except ValueError:
        utils.printerr('"{}" is not a valid index!'.format(ind))
        return
    if ind >= len(interpreters):
        utils.printerr('Index {} is out of bounds (max: {})!'.format(ind, len(interpreters)-1))
        return
    interpreters[ind].kill()
    del interpreters[ind]

def on_stop_filter(cmd: pcmd.Command, args: List[str], ind: str) -> None:
    """Callback for `stop filter` - stops a running filter"""
    if ind.lower() in ('a', 'all'):
        ch.del_all_filters()
        return
    try:
        ind = int(ind)
    except ValueError:
        utils.printerr('"{}" is not a valid index!'.format(ind))
        return
    filters = ch.get_filters()
    if ind >= len(filters):
        utils.printerr('Index {} is out of bounds (max: {})!'.format(ind, len(filters)-1))
        return
    ch.del_filter(ind)

def on_start(cmd: pcmd.Command, args: List[str], json: bool) -> None:
    """Callback for `start` - starts the channel"""
    global ch
    if ch.is_alive():
        if not json:
            utils.printwrn('Already running ... ')
        else:
            print(JSON.dumps({ 'error': 'Already running ... ', }))
        return
    ch = Channel(ch.transf, ch.ist, ch.ost)
    server.ch = ch
    try:
        ch.start()
        if json:
            print(JSON.dumps({}))
    except IOError as e:
        if not json:
           utils.printerr(e)
        else:
            print(JSON.dumps({ 'error': str(e), }))

def on_stop(cmd: pcmd.Command, args: List[str], json: bool) -> None:
    """Callback for `stop` - stops the channel"""
    if not ch.is_alive():
        if not json:
            utils.printwrn('Not running ... ')
        else:
            print(JSON.dumps({ 'error': 'Not running ... ', }))
        return
    ch.kill()
    if json:
        print(JSON.dumps({}))

def _with_json(c: pcmd.Command) -> pcmd.Command:
    c.add_arg('--json', action='store_true')
    return c

def start() -> None:
    """Start prompting the user for input."""
    # ---------------------------------------------------------------------------------------------------------------------- #
    sh.add_cmd(pcmd.Command('clear', 'cls', callback=pash.cmds.clear, hint='Clear the console ... '))
    # ---------------------------------------------------------------------------------------------------------------------- # 
    sh.add_cmd(pcmd.Command('exit', 'quit', 'exit()', callback=on_exit, hint='Quit the shell ... '))
    # ---------------------------------------------------------------------------------------------------------------------- #
    show_audio = pcmd.Command('audio', callback=on_show_audio, hint='Show what audio input is detected ... ')
    show_audio.add_arg('-s', '--scale', type=float, dest='scale', default=5., help='Specify output scale ... ')
    show_audio.add_arg('-c', '--char', type=str, dest='char', default='▬', help='Specify the character to be used for the graph ... ')
    sh.add_cmd(pcmd.CascCommand('show', 'sh', cmds=[
        _with_json(pcmd.Command('devices', 'dev', callback=on_show_devices, hint='List all devices ... ')),
        show_audio,
        _with_json(pcmd.Command('status', 'stat', callback=on_show_status, hint='Show the audio channel\'s status ... ')),
        _with_json(pcmd.CascCommand('sounds', cmds=[
            _with_json(pcmd.Command('all', 'a', callback=on_show_all_sounds, hint='List all available sounds ... ')),
        ], callback=on_show_sounds, hint='List all currently playing sounds ... ')),
        pcmd.Command('interpreters', 'in', callback=on_show_interpreters, hint='List all running/available interpreters ... '),
        _with_json(pcmd.CascCommand('filters', 'fil', cmds=[
            _with_json(pcmd.Command('all', 'a', callback=on_show_all_filters, hint='List all available voice filters ... ')),
        ], callback=on_show_running_filters, hint='List all running/available voice filters ... ')),
    ], hint='Show info ... '))
    # ---------------------------------------------------------------------------------------------------------------------- #
    start_sound = pcmd.Command('sound', callback=on_start_sound, hint='Play a soundeffect ... ')
    start_sound.add_arg('parameters', type=str, nargs='*', help='Specify the filenames & volumes ... ')
    start_output = pcmd.Command('output', 'ost', callback=on_start_output, hint='Add an output device ... ')
    start_output.add_arg('indo', type=int, help='Specify the output device\'s index ... ')
    start_input = pcmd.Command('input', 'ist', callback=on_start_input, hint='Add an input device ... ')
    start_input.add_arg('indi', type=int, help='Specify the input device\'s index ... ')
    start_interpreter = pcmd.Command('interpreter', 'in', callback=on_start_interpreter, hint='Interpret a .fig file ... ')
    start_interpreter.add_arg('fname', type=str, help='Specify the filenames ... ')
    start_filter = pcmd.Command('filter', 'fil', callback=on_start_filter, hint='Add a filter to your audio input ... ')
    start_filter.add_arg('name', type=str, help='Specify the filter\'s name ... ')
    start_filter.add_arg('cargs', nargs='*', help='Specify the filter\'s arguments ... ')
    sh.add_cmd(_with_json(pcmd.CascCommand('start', cmds=[
        _with_json(start_sound),
        _with_json(start_output),
        _with_json(start_input),
        start_interpreter,
        start_filter,
        pcmd.Command('server', 'srv', callback=on_start_server, hint='Start the websocket server ... ')
    ], callback=on_start, hint='Start channeling audio / other things ... ')))
    # ---------------------------------------------------------------------------------------------------------------------- #
    stop_sound = pcmd.Command('sound', callback=on_stop_sound, hint='Remove a soundeffect ... ')
    stop_sound.add_arg('ind', type=str, help='Specify the sound effect\'s index ... ')
    stop_output = pcmd.Command('output', 'ost', callback=on_stop_output, hint='Remove an output device ... ')
    stop_output.add_arg('indo', type=int, help='Specify the output device\'s index ... ')
    stop_input = pcmd.Command('input', 'ist', callback=on_stop_input, hint='Remove an input device ... ')
    stop_input.add_arg('indi', type=int, help='Specify the input device\'s index ... ')
    stop_interpreter = pcmd.Command('interpreter', 'in', callback=on_stop_interpreter, hint='Stop a running interpreter ... ')
    stop_interpreter.add_arg('ind', type=str, help='Specify the interpreter\'s index ... ')
    stop_filter = pcmd.Command('filter', 'fil', callback=on_stop_filter, hint='Stop a running filter ... ')
    stop_filter.add_arg('ind', type=str, help='Specify the filter\'s index ... ')
    sh.add_cmd(_with_json(pcmd.CascCommand('stop', 'kill', cmds=[
        _with_json(stop_sound),
        _with_json(stop_output),
        _with_json(stop_input),
        stop_interpreter,
        stop_filter,
    ], callback=on_stop, hint='Stop channeling audio / other things ... ')))
    # ---------------------------------------------------------------------------------------------------------------------- #
    sh.prompt_until_exit()