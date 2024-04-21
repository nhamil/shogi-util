import argparse
import collections
import os 
import signal
import subprocess
import sys 
import threading

DEBUG = False 

USI_INFO_KEYWORDS = {
    'depth', 
    'seldepth', 
    'time', 
    'nodes', 
    'pv', 
    'multipv', 
    'score', 
    'cp', 
    'mate', 
    'lowerbound', 
    'upperbound', 
    'currmove', 
    'currmovenumber', 
    'hashfull', 
    'nps', 
    'cpuload', 
    'string', 
    'refutation', 
    'currline' 
}

USI_INFO_MOVE_KEYWORDS = {
    'pv', 
    'currmove', 
    'refutation', 
    'currline'
}

USI_TO_UCI_OPTIONS = {
    'USI_Hash': 'Hash', 
    'USI_Variant': 'UCI_Variant'
}

UCI_TO_USI_OPTIONS = {
    'Hash': 'USI_Hash', 
    'UCI_Variant': 'USI_Variant'
}

HAND_ORDER = [
    'R', 'B', 'G', 'S', 'N', 'L', 'P', 
    'r', 'b', 'g', 's', 'n', 'l', 'p'
]

def log(msg): 
    if not DEBUG: return 
    sys.stderr.write(msg + '\n') 
    sys.stderr.flush() 

def base_cmd_replacer(new_cmd): 
    def replacer(cmd): 
        cmd[0] = new_cmd 
        return cmd 
    return replacer

def usi_to_uci_square(square): 
    col = 8 - (ord(square[0]) - ord('1')) 
    row = 8 - (ord(square[1]) - ord('a')) 
    return chr(ord('a') + col) + chr(ord('1') + row)

def usi_to_uci_move(move): 
    if move == '0000': 
        return move 
    try: 
        sq_from = move[0:2]
        sq_to = move[2:4]
        piece = move[0]
        promote = move[1]
        if promote == '*': 
            out = piece 
            out += '@' 
            out += usi_to_uci_square(sq_to) 
            out += move[4:] 
            move = out 
        else: # Normal move 
            out = usi_to_uci_square(sq_from)
            out += usi_to_uci_square(sq_to)
            out += move[4:]
            move = out 
    except Exception as e: 
        log("-- Expected move but could not parse: " + move + ": " + str(e) + " --") 
        pass 
    return move 

def uci_to_usi_square(square): 
    col = 8 - (ord(square[0]) - ord('a')) 
    row = 8 - (ord(square[1]) - ord('1')) 
    return chr(ord('1') + col) + chr(ord('a') + row)

def uci_to_usi_move(move): 
    if move == '0000': 
        return move 
    try: 
        sq_from = move[0:2]
        sq_to = move[2:4]
        piece = move[0]
        promote = move[1]
        if promote == '@': 
            out = piece 
            out += '*' 
            out += uci_to_usi_square(sq_to) 
            out += move[4:] 
            move = out 
        else: # Normal move 
            out = uci_to_usi_square(sq_from)
            out += uci_to_usi_square(sq_to)
            out += move[4:]
            move = out 
    except Exception as e: 
        log("-- Expected move but could not parse: " + move + ": " + str(e) + " --") 
        pass 
    return move 

def usi_to_uci_bestmove(cmd): 
    if len(cmd) < 2: 
        return cmd 

    cmd[1] = usi_to_uci_move(cmd[1])
    return cmd 

def usi_to_uci_info(cmd): 
    convert_move = False 
    convert_mate = False 

    for i in range(len(cmd)): 
        term = cmd[i]

        if term in USI_INFO_KEYWORDS: 
            convert_move = False 
            convert_mate = False 

        if convert_mate: 
            log("-- TODO Convert mate from ply to turn --")

        if convert_move: 
            cmd[i] = usi_to_uci_move(term)

        if term == 'mate': 
            convert_mate = True 
        elif term in USI_INFO_MOVE_KEYWORDS: 
            convert_move = True 
        elif term == 'string': 
            # Rest of the line is ignored 
            break 

    return cmd 

def usi_to_uci_option(cmd): 
    if len(cmd) < 3 or cmd[1] != 'name': 
        return cmd 

    cmd[2] = USI_TO_UCI_OPTIONS.get(cmd[2], cmd[2])

    # USI added 'filename' type 
    if len(cmd) >= 5 and cmd[3] == 'type' and cmd[4] == 'filename': 
        cmd[4] = 'string'

    return cmd

def uci_to_usi_setoption(cmd): 
    if len(cmd) < 3 or cmd[1] != 'name': 
        return cmd 

    name_mode = True 
    name = [] 
    after = [] 

    # UCI options can have spaces so get the whole name
    for term in cmd[2:]: 
        if term == 'value': 
            name_mode = False 

        if name_mode: 
            name.append(term) 
        else: 
            after.append(term) 

    # USI options may not have spaces 
    name = '_'.join(name) 
    name = UCI_TO_USI_OPTIONS.get(name, name)

    return cmd[:2] + [name] + after

def fen_to_sfen(fen): 
    cmd = fen.split(' ') 
    board = cmd[0]
    hand = '-'
    turn = ''
    move_num = '1'

    # Separate hand and convert it to SFEN style
    if '[' in board: 
        board = board.replace(']', '').split('[') 
        hand_count = collections.defaultdict(int) 

        # FEN hand lists n chars for n pieces (2R4p = RRpppp)
        for piece in board[1]: 
            hand_count[piece] += 1

        hand_str = ''
        for piece in HAND_ORDER: 
            if hand_count[piece] == 1: 
                hand_str += piece 
            elif hand_count[piece] > 1: 
                hand_str += str(hand_count[piece]) + piece 
        if len(hand_str) != 0: 
            hand = hand_str

        board = board[0] 

    # Colors are swapped 
    if len(cmd) >= 2: 
        turn = cmd[1] 
        if turn == 'w': 
            turn = 'b' 
        elif turn == 'b': 
            turn = 'w' 

    # Turn number 
    try: 
        if len(cmd) >= 4 and cmd[3].isdigit(): # isdigit returns False for '-' which is what we want 
            move_num = cmd[3] 
        if len(cmd) >= 6 and cmd[5].isdigit(): # isdigit returns False for '-' which is what we want 
            move_num = cmd[5] 
        move_num = int(move_num) * 2 - 1
        if turn == 'w': 
            move_num += 1
        move_num = str(move_num) 
    except: 
        pass 

    return ' '.join([board, turn, hand, move_num])

def uci_to_usi_position(cmd): 
    if len(cmd) < 3: 
        return cmd 

    out = ['position']
    fen = [] 
    fen_mode = False 
    move_mode = False 

    for term in cmd[1:]: 
        if term == 'fen': 
            fen_mode = True 
            move_mode = False 
            out.append('sfen') 
            continue 

        if term == 'moves': 
            if len(fen) > 0: 
                out.append(fen_to_sfen(' '.join(fen)))
                fen = [] 
            fen_mode = False 
            move_mode = True 
            out.append('moves') 
            continue 

        if fen_mode: 
            fen.append(term)
        elif move_mode: 
            out.append(uci_to_usi_move(term))
        else: 
            out.append(term) 

    # If there were no moves after the FEN then it hasn't been added 
    if len(fen) > 0: 
        out.append(fen_to_sfen(' '.join(fen)))
        fen = [] 

    return out 

UCI_TO_USI = {
    'uci': base_cmd_replacer('usi'), 
    'ucinewgame': base_cmd_replacer('usinewgame'), 
    'setoption': uci_to_usi_setoption, 
    'position': uci_to_usi_position, 
}

USI_TO_UCI = {
    'usiok': base_cmd_replacer('uciok'), 
    'bestmove': usi_to_uci_bestmove, 
    'info': usi_to_uci_info, 
    'option': usi_to_uci_option, 
}

def usi_to_uci(cmd): 
    if cmd[0] in USI_TO_UCI: 
        cmd = USI_TO_UCI[cmd[0]](cmd)

    return cmd

def uci_to_usi(cmd): 
    if cmd[0] in UCI_TO_USI: 
        cmd = UCI_TO_USI[cmd[0]](cmd)

    log("-- To engine: " + ' '.join(cmd) + " --")
    return cmd

def process_lines(f_in, f_out): 
    try: 
        while not f_in.closed and not f_out.closed: 
            try: 
                line = f_in.readline().decode()
            except: 
                break 

            if len(line) == 0: 
                break 

            words = line.rstrip().split(' ')
            out = ' '.join(usi_to_uci(words)) + '\n'
            f_out.write(out.encode())
            f_out.flush()
    except: 
        pass 
    os.kill(os.getpid(), signal.SIGINT); 

def main_cli(): 
    sys.stdout.reconfigure(line_buffering=True)

    parser = argparse.ArgumentParser()
    parser.add_argument('engine', type=str, help="The engine command")
    parser.add_argument('args', nargs='*', type=str, default=[], help="Arguments to pass to the engine")
    args = parser.parse_args()

    cmd = [args.engine, *args.args]
    log(f"-- Running command {' '.join(cmd)} --") 

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stdin=subprocess.PIPE)
    t_out = threading.Thread(
        target=process_lines, 
        args=(proc.stdout, sys.stdout.buffer), 
        daemon=True
    )
    t_out.start()

    try: 
        while True: 
            line = sys.stdin.readline() 
            if len(line) == 0: 
                break 
            words = line.rstrip().split(' ')
            out = ' '.join(uci_to_usi(words)) + '\n' 
            proc.stdin.write(out.encode()) 
            proc.stdin.flush()
    except: 
        pass 

    try: 
        t_out.join()
    except: 
        pass 

if __name__ == '__main__': 
    main_cli() 

