#!/usr/bin/env python3

import argparse
import itertools
import json
import logging
import os
import re
import shlex
import subprocess
import sys
import glob
from pathlib import Path
from math import floor, ceil, log
from fractions import Fraction

UPLOAD_KEY_REQUEST_ENDPOINT = 'https://api.gfycat.com/v1/gfycats?'
FILE_UPLOAD_ENDPOINT = 'https://filedrop.gfycat.com'
AUTHENTICATION_ENDPOINT = 'https://api.gfycat.com/v1/oauth/token'

__version__ = '3.6.3'

settings = {}

outPaths = []
fileNames = []
links = []
markdown = ''

ffmpegPath = 'ffmpeg'
ffprobePath = 'ffprobe'
ffplayPath = 'ffplay'
webmsPath = './webms'
logger = None

if getattr(sys, 'frozen', False):
    ffmpegPath = './bin/ffmpeg'
    ffprobePath = './bin/ffprobe'
    ffplayPath = './bin/ffplay'
    if sys.platform == 'win32':
        ffmpegPath += '.exe'
        ffprobePath += '.exe'
        ffplayPath += '.exe'
    if sys.platform == 'darwin':
        os.environ['SSL_CERT_FILE'] = "certifi/cacert.pem"


def main():
    global settings, webmsPath
    args, unknown = buildArgParser()
    if args.cropMultiple != 1:
        args.cropMultipleX = args.cropMultiple
        args.cropMultipleY = args.cropMultiple

    args = vars(args)

    args = {k: v for k, v in args.items() if v is not None}

    args["videoStabilization"] = getVidstabPreset(
        args["videoStabilization"], args["videoStabilizationDynamicZoom"])
    args["denoise"] = getDenoisePreset(args["denoise"])
    settings = {'markerPairMergeList': '', 'rotate': 0,
                'overlayPath': '', 'delay': 0, 'color_space': None, **args}

    settings["isDashVideo"] = False
    settings["isDashAudio"] = False
    if "enableSpeedMaps" not in settings:
        settings["enableSpeedMaps"] = not settings["noSpeedMaps"]

    with open(settings["json"], 'r', encoding='utf-8-sig') as file:
        markersJson = file.read()
        settings = loadMarkers(markersJson, settings)
    settings["videoTitle"] = re.sub('"', '',  settings["videoTitle"])
    settings["markersDataFileStem"] = Path(settings["json"]).stem
    settings["titleSuffix"] = settings["markersDataFileStem"]
    webmsPath += f'/{settings["titleSuffix"]}'

    os.makedirs(f'{webmsPath}', exist_ok=True)
    setUpLogger()

    logger.info(f'Version: {__version__}')
    logger.info('-' * 80)

    settings["downloadVideoNameStem"] = f'{settings["titleSuffix"]}-full'
    settings["downloadVideoPath"] = f'{webmsPath}/{settings["downloadVideoNameStem"]}'
    pivpat = r'^' + re.escape(settings["downloadVideoNameStem"]) + r'\.[^.]+$'
    potentialInputVideos = [
        f'{webmsPath}/{iv}' for iv in os.listdir(webmsPath) if re.search(pivpat, iv)]

    settings["automaticFetching"] = not settings["inputVideo"] and not settings["downloadVideo"]

    if settings["automaticFetching"] and not settings["preview"] and not settings["noAutoFindInputVideo"]:
        if len(potentialInputVideos) > 0:
            logger.info(
                f'Found potential input video at path {potentialInputVideos[0]}.')
            if len(potentialInputVideos) > 1:
                logger.warning(
                    f'Also found the following other potential input videos {potentialInputVideos[1:]}.')
            settings["inputVideo"] = potentialInputVideos[0]

    if settings["automaticFetching"] and settings["preview"]:
        logger.warning(
            "Preview mode was enabled without providing a local input video and video downloading disabled.")
        logger.warning(
            "Automatic fetching of video stream chunks provides a poor preview experience.")
        logger.warning(
            "Automatically fetched video previews can only loop up to 32767 frames (~9 min at 60fps).")
        logger.warning(
            "When previewing, a local video file uses less memory and does not require re-streaming from the internet on seek with right-click.")
        logger.warning(
            "A local video also enables toggling of video correction filters with W.")
        if not settings["noAutoFindInputVideo"]:
            if len(potentialInputVideos) > 0:
                logger.info(
                    f'Found potential input video at path {potentialInputVideos[0]}.')
                useFoundInputVideo = input(
                    r'Would you like to use this input video? (y/n): ')
                if useFoundInputVideo == 'yes' or useFoundInputVideo == 'y':
                    settings["inputVideo"] = potentialInputVideos[0]

        if not settings["inputVideo"]:
            try:
                logger.info(
                    "You may be able to drag and drop the input video file at the following prompt.")
                settings["inputVideo"] = input(
                    f'Specify an input video path OR press ENTER to continue without doing so: ')
                if settings["inputVideo"] == '':
                    logger.info(
                        f'The video can also be downloaded before previewing to the path: "{settings["downloadVideoPath"]}"')
                    logger.info(
                        "Note the file extension will be automatically determined.")
                    logger.info(
                        "If the file already exists it will be used as is without re-downloading.")
                    downloadVideo = input(
                        f'Would you like to automatically download the video? (y/n): ')
                    if downloadVideo == 'yes' or downloadVideo == 'y':
                        settings["downloadVideo"] = True
            except:
                pass

    if settings["inputVideo"]:
        if not Path(settings["inputVideo"]).is_file():
            logger.error(
                f'Input video file "{settings["inputVideo"]}" does not exist or is not a file.')
            logger.error(f'Exiting...')
            sys.exit(1)
        else:
            logger.info(
                f'Automatically using found input video file "{settings["inputVideo"]}".')

        settings = getVideoInfo(settings, {})
    else:
        settings = prepareGlobalSettings(settings)

    if not settings["preview"]:
        for markerPairIndex, marker in enumerate(settings["markerPairs"]):
            settings["markerPairs"][markerPairIndex] = makeMarkerPairClip(
                settings, markerPairIndex)
        if settings["markerPairMergeList"] != '':
            makeMergedClips(settings)
    else:
        while True:
            try:
                inputStr = input(
                    f'Enter a valid marker pair number (between {1} and {len(settings["markerPairs"])}) or quit(q): ')
                if inputStr == 'quit' or inputStr == 'q':
                    break
                markerPairIndex = int(inputStr)
                markerPairIndex -= 1
            except ValueError:
                logger.error(f'{inputStr} is not a valid number.')
                continue
            if 0 <= markerPairIndex < len(settings["markerPairs"]):
                makeMarkerPairClip(settings, markerPairIndex)
            else:
                logger.error(
                    f'{markerPairIndex + 1} is not a valid marker pair number.')
            continue


def setUpLogger():
    global logger
    loggerHandlers = [logging.StreamHandler()]
    if not settings["preview"]:
        loggerHandlers.append(logging.FileHandler(
            filename=f'{webmsPath}/{settings["titleSuffix"]}.log', mode='a', encoding='utf-8'))
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt="%y-%m-%d %H:%M:%S",
        handlers=loggerHandlers)
    logger = logging.getLogger()


def buildArgParser():
    parser = argparse.ArgumentParser(
        description='Generate trimmed webms from input video.')
    parser.add_argument('--input-video', '-i', dest='inputVideo', default='',
                        help='Input video path.')
    parser.add_argument('--download-video', '-dv', action='store_true', dest='downloadVideo',
                        help='Download video from the internet and use as input video for processing marker data.')
    parser.add_argument('--markers-json', '-j', required=True, dest='json',
                        help=('Specify markers json path for generating webms from input video.' +
                              'Automatically streams required portions of input video from the internet if it is not otherwise specified.'))
    parser.add_argument('--overlay', '-o', dest='overlay',
                        help='overlay image path')
    parser.add_argument('--multiply-crop', '-mc', type=float, dest='cropMultiple', default=1,
                        help=('Multiply all crop dimensions by an integer. ' +
                              '(Helpful if you change resolutions: eg 1920x1080 * 2 = 3840x2160(4k)).'))
    parser.add_argument('--multiply-crop-x', '-mcx', type=float, dest='cropMultipleX', default=1,
                        help='Multiply all x crop dimensions by an integer.')
    parser.add_argument('--multiply-crop-y', '-mcy', type=float, dest='cropMultipleY', default=1,
                        help='Multiply all y crop dimensions by an integer.')
    parser.add_argument('--gfycat', '-gc', action='store_true',
                        help='upload all output webms to gfycat and print reddit markdown with all links')
    parser.add_argument('--audio', '-a', action='store_true',
                        help='Enable audio in output webms.')
    parser.add_argument('--format', '-f', default='bestvideo+(bestaudio[acodec=opus]/bestaudio[acodec=vorbis]/bestaudio)',
                        help='Specify format string passed to youtube-dl.')
    parser.add_argument('--extra-video-filters', '-evf', dest='extraVideoFilters', default='',
                        help='Specify any extra video filters to be passed to ffmpeg.')
    parser.add_argument('--delay', '-d', type=float, dest='delay', default=0,
                        help='Add a fixed delay to both the start and end time of each marker. Can be negative.')
    parser.add_argument('--gamma', '-ga', type=float, dest='gamma', default=1,
                        help='Apply luminance gamma correction. Pass in a value between 0 and 1 to brighten shadows and reveal darker details.')
    parser.add_argument('--rotate', '-r', choices=['clock', 'cclock'],
                        help='Rotate video 90 degrees clockwise or counter-clockwise.')
    parser.add_argument('--denoise', '-dn', type=int, default=0, choices=range(0, 6),
                        help='Apply the hqdn3d denoise filter using a preset strength level from 0-5 where 0 is disabled and 5 is very strong.')
    parser.add_argument('--video-stabilization', '-vs', dest='videoStabilization', type=int, default=0, choices=range(0, 7),
                        help='Apply video stabilization using a preset strength level from 0-6 where 0 is disabled and 6 is strongest.')
    parser.add_argument('--video-stabilization-dynamic-zoom', '-vsdz', dest='videoStabilizationDynamicZoom', type=bool, default=False,
                        help='Enable video stabilization dynamic zoom. Unlike a static zoom the zoom in can vary with time to reduce cropping of video.')
    parser.add_argument('--deinterlace', '-di', action='store_true',
                        help='Apply bwdif deinterlacing.')
    parser.add_argument('--expand-color-range', '-ecr', dest='expandColorRange', action='store_true',
                        help='Expand the output video color range to full (0-255).')
    parser.add_argument('--loop', '-l', dest='loop', choices=['none', 'fwrev', 'fade'], default='none',
                        help='Apply special looping effect to marker pair clips. For a forward-reverse or ping-pong loop use fwrev. For a cross-fading loop use fade.')
    parser.add_argument('--fade-duration', '-fd', type=float, dest='fadeDuration', default=0.5,
                        help=('When cross-fading loop is enabled set the duration over which to cross-fade the end and start of the clip. '
                              + 'The fade duration is clamped to a minimum of 0.1 seconds and a maximum of 40%% of the output clip duration.'))
    parser.add_argument('--encode-speed', '-s', type=int, dest='encodeSpeed', choices=range(0, 6),
                        help='Set the vp9 encoding speed.')
    parser.add_argument('--crf', type=int,
                        help=('Set constant rate factor (crf). Default is 30 for video file input.' +
                              'Automatically set to a factor of the detected video bitrate'))
    parser.add_argument('--two-pass', '-tp', dest='twoPass', action='store_true',
                        help='Enable two-pass encoding. Improves quality at the cost of encoding speed.')
    parser.add_argument('--target-max-bitrate', '-b', dest='targetMaxBitrate', type=int,
                        help=('Set target max bitrate in kilobits/s. Constrains bitrate of complex scenes.' +
                              'Automatically set based on detected video bitrate.'))
    parser.add_argument('--no-auto-scale-crop-res', '-nascr', dest='noAutoScaleCropRes', action='store_true',
                        help=('Disable automatically scaling the crop resolution when a mismatch with video resolution is detected.'))
    parser.add_argument('--preview', '-p', action='store_true',
                        help=('Pass in semicolon separated lists of marker pairs.'
                              + 'Lists of marker pairs are comma-separated numbers or dash separated ranges. (eg 1-3,7;4-6,9)'))
    parser.add_argument('--no-auto-find-input-video', '-nafiv', dest='noAutoFindInputVideo', action='store_true',
                        help='Disable automatic detection and usage of input video when not in preview mode.')
    parser.add_argument('--no-speed-maps', '-nsm', dest='noSpeedMaps', action='store_true',
                        help='Disable speed maps for time-variable speed.')
    return parser.parse_known_args()


def loadMarkers(markersJson, settings):
    markersDict = json.loads(markersJson)
    settings = {**settings, **markersDict}
    if "markers" in settings and not "markerPairs" in settings:
        settings["markerPairs"] = settings["markers"]
    settings["videoURL"] = 'https://www.youtube.com/watch?v=' + \
        settings["videoID"]

    return settings


def getVideoURL(settings):
    from youtube_dl import YoutubeDL

    ydl_opts = {'format': settings["format"], 'forceurl': True,
                'ffmpeg_location': ffmpegPath, 'merge_output_format': 'mkv',
                'outtmpl': f'{settings["downloadVideoPath"]}.%(ext)s', "cachedir": False}
    ydl = YoutubeDL(ydl_opts)
    if settings["downloadVideo"]:
        ydl_info = ydl.extract_info(settings["videoURL"], download=True)
        settings["downloadVideoPath"] = f'{settings["downloadVideoPath"]}.mkv'
    else:
        ydl_info = ydl.extract_info(settings["videoURL"], download=False)

    if 'requested_formats' in ydl_info:
        rf = ydl_info["requested_formats"]
        videoInfo = rf[0]
    else:
        videoInfo = ydl_info

    dashFormatIDs = []
    dashVideoFormatID = None
    dashAudioFormatID = None

    if settings["downloadVideo"]:
        settings["inputVideo"] = settings["downloadVideoPath"]
    else:
        if videoInfo["protocol"] == 'http_dash_segments':
            settings["isDashVideo"] = True
            dashVideoFormatID = videoInfo["format_id"]
            dashFormatIDs.append(dashVideoFormatID)
        else:
            settings["videoURL"] = videoInfo["url"]

        if 'requested_formats' in ydl_info:
            audioInfo = rf[1]
            settings["audiobr"] = int(audioInfo["tbr"])

            if audioInfo["protocol"] == 'http_dash_segments':
                settings["isDashAudio"] = True
                dashAudioFormatID = audioInfo["format_id"]
                dashFormatIDs.append(dashAudioFormatID)
            else:
                settings["audioURL"] = audioInfo["url"]

        if dashFormatIDs:
            filteredDashPath = filterDash(videoInfo["url"], dashFormatIDs)
            if settings["isDashVideo"]:
                settings["videoURL"] = filteredDashPath
            if settings["isDashAudio"]:
                settings["audioURL"] = filteredDashPath

    return getVideoInfo(settings, videoInfo)


def getVideoInfo(settings, videoInfo):
    if settings["inputVideo"]:
        probedSettings = ffprobeVideoProperties(settings["inputVideo"])
    else:
        probedSettings = ffprobeVideoProperties(settings["videoURL"])

    if probedSettings is not None:
        settings = {**settings, **videoInfo, **probedSettings}
    else:
        if not videoInfo:
            logger.error(
                "Could not fetch local input video info with ffprobe.")
        settings = {**settings, **videoInfo}

    if settings["isDashVideo"] or not "bit_rate" in settings:
        settings["bit_rate"] = int(videoInfo["tbr"])

    if not "r_frame_rate" in settings:
        settings["r_frame_rate"] = videoInfo["fps"]

    logger.info(f'Video Title: {settings["videoTitle"]}')
    logger.info(f'Video Width: {settings["width"]}')
    logger.info(f'Video Height: {settings["height"]}')
    logger.info(f'Video fps: {settings["r_frame_rate"]}')
    logger.info(f'Detected Video Bitrate: {settings["bit_rate"]}kbps')

    settings = autoSetCropMultiples(settings)

    return settings


def prepareGlobalSettings(settings):
    logger.info(f'Video URL: {settings["videoURL"]}')
    logger.info(
        f'Merge List: {settings["markerPairMergeList"] if settings["markerPairMergeList"] else "None"}')

    settings = getVideoURL(settings)
    encodeSettings = getDefaultEncodeSettings(settings["bit_rate"])

    logger.info('-' * 80)
    unknownColorSpaceMsg = "unknown (bt709 will be assumed for color range operations)"
    logger.info((f'Automatically determined encoding settings: CRF: {encodeSettings["crf"]} (0-63), ' +
                 f'Auto Target Max Bitrate: {encodeSettings["autoTargetMaxBitrate"]}kbps, ' +
                 f'Detected Color Space: {settings["color_space"] if settings["color_space"] else  unknownColorSpaceMsg}, ' +
                 f'Two-pass Encoding Enabled: {encodeSettings["twoPass"]}, ' +
                 f'Encoding Speed: {encodeSettings["encodeSpeed"]} (0-5)'))

    settings = {**encodeSettings, **settings}

    logger.info('-' * 80)
    logger.info((f'Global Encoding Settings: CRF: {settings["crf"]} (0-63), ' +
                 f'Detected Bitrate: {settings["bit_rate"]}kbps, ' +
                 f'Global Target Max Bitrate: {str(settings["targetMaxBitrate"]) + "kbps" if "targetMaxBitrate" in settings else "None"}, ' +
                 f'Two-pass Encoding Enabled: {settings["twoPass"]}, Encoding Speed: {settings["encodeSpeed"]} (0-5), ' +
                 f'Audio Enabled: {settings["audio"]}, Denoise: {settings["denoise"]["desc"]}, Rotate: {settings["rotate"]}, ' +
                 f'Expand Color Range Enabled: {settings["expandColorRange"]}, ' +
                 f'Speed Maps Enabled: {settings["enableSpeedMaps"]}, ' +
                 f'Special Looping: {settings["loop"]}, ' +
                 (f'Fade Duration: {settings["fadeDuration"]}, ' if settings["loop"] == 'fade' else '') +
                 f'Video Stabilization: {settings["videoStabilization"]["desc"]}, ' +
                 f'Video Stabilization Dynamic Zoom: {settings["videoStabilizationDynamicZoom"]}'))
    return settings


def getMarkerPairSettings(settings, markerPairIndex):
    mp = markerPair = {**(settings["markerPairs"][markerPairIndex])}

    cropString = mp["crop"]
    crops = mp["cropComponents"] = cropString.split(':')
    crops[0] = settings["cropMultipleX"] * int(crops[0])
    if crops[2] != 'iw':
        crops[2] = settings["cropMultipleX"] * int(crops[2])
    else:
        crops[2] = settings["width"]
    crops[1] = settings["cropMultipleY"] * int(crops[1])
    if crops[3] != 'ih':
        crops[3] = settings["cropMultipleY"] * int(crops[3])
    else:
        crops[3] = settings["height"]

    bitrateCropFactor = (crops[2] * crops[3]) / \
        (settings["width"] * settings["height"])
    markerPairEncodeSettings = getDefaultEncodeSettings(
        settings["bit_rate"] * bitrateCropFactor)
    settings = {**markerPairEncodeSettings, **settings}

    if "targetMaxBitrate" in settings:
        settings["autoTargetMaxBitrate"] = getDefaultEncodeSettings(
            settings["targetMaxBitrate"] * bitrateCropFactor)["autoTargetMaxBitrate"]
    else:
        settings["autoTargetMaxBitrate"] = markerPairEncodeSettings["autoTargetMaxBitrate"]

    mps = markerPairSettings = {**settings, **(mp["overrides"])}

    mp["exists"] = False
    if not mps["preview"]:
        if "titlePrefix" in mps:
            mps["titlePrefix"] = cleanFileName(mps["titlePrefix"])
        mp["fileNameStem"] = f'{mps["titlePrefix"] + "-" if "titlePrefix" in mps else ""}{mps["titleSuffix"]}-{markerPairIndex + 1}'
        mp["fileName"] = f'{mp["fileNameStem"]}.webm'
        mp["filePath"] = f'{webmsPath}/{mp["fileName"]}'
        if checkWebmExists(mp["fileName"], mp["filePath"]):
            mp["exists"] = True
            return (markerPair, markerPairSettings)

    mp["start"] = mp["start"] + mps["delay"]
    mp["end"] = mp["end"] + mps["delay"]
    mp["duration"] = mp["end"] - mp["start"]

    mp["isVariableSpeed"] = False
    if mps["enableSpeedMaps"] and "speedMap" in mp:
        for left, right in zip(mp["speedMap"][:-1], mp["speedMap"][1:]):
            if left["y"] != right["y"]:
                mp["isVariableSpeed"] = True
                break
    else:
        mp["speedMap"] = [{"x": mp["start"], "y":mp["speed"]}, {
            "x": mp["end"], "y":mp["speed"]}]

    if mps["loop"] == 'fwrev':
        mp["isVariableSpeed"] = False

    mp["speedFilter"], mp["outputDuration"] = getSpeedFilterAndDuration(
        mp["speedMap"], mps, mps["r_frame_rate"])

    titlePrefixLogMsg = f'Title Prefix: {mps["titlePrefix"] if "titlePrefix" in mps else ""}'
    logger.info('-' * 80)
    logger.info((f'Marker Pair {markerPairIndex + 1} Settings: {titlePrefixLogMsg}, ' +
                 f'CRF: {mps["crf"]} (0-63), Bitrate Crop Factor: {bitrateCropFactor}, ' +
                 f'Crop Adjusted Target Max Bitrate: {mps["autoTargetMaxBitrate"]}kbps, ' +
                 f'Two-pass Encoding Enabled: {mps["twoPass"]}, Encoding Speed: {mps["encodeSpeed"]} (0-5), ' +
                 f'Expand Color Range Enabled: {mps["expandColorRange"]}, ' +
                 f'Audio Enabled: {mps["audio"]}, Denoise: {mps["denoise"]["desc"]}, ' +
                 f'Marker Pair {markerPairIndex + 1} is of variable speed: {mp["isVariableSpeed"]}, ' +
                 f'Speed Maps Enabled: {mps["enableSpeedMaps"]}, ' +
                 f'Special Looping: {mps["loop"]},  ' +
                 (f'Fade Duration: {mps["fadeDuration"]}s' if mps["loop"] == 'fade' else '') +
                 f'Final Output Duration: {mp["outputDuration"]}, ' +
                 f'Video Stabilization: {mps["videoStabilization"]["desc"]}, ' +
                 f'Video Stabilization Dynamic Zoom: {mps["videoStabilizationDynamicZoom"]}'))
    logger.info('-' * 80)

    return (markerPair, markerPairSettings)


def makeMarkerPairClip(settings, markerPairIndex):
    mp, mps = getMarkerPairSettings(settings, markerPairIndex)

    if mp["exists"]:
        return {**(settings["markerPairs"][markerPairIndex]), **mp}

    inputs = ''
    audio_filter = ''
    video_filter = ''

    if mp["isVariableSpeed"] or mps["loop"] != 'none':
        mps["audio"] = False

    reconnectFlags = r'-reconnect 1 -reconnect_at_eof 1 -reconnect_streamed 1 -reconnect_delay_max 5'
    if mps["audio"]:
        # ffplay previewing does not support multiple inputs
        # if an input video is provided, a dash xml is used, or previewing is on, there is only one input
        if not mps["inputVideo"] and not settings["isDashAudio"] and not settings["preview"]:
            inputs += reconnectFlags
            inputs += f' -ss {mp["start"]} -i "{mps["audioURL"]}" '

        # preview mode does not start each clip at time 0 unlike encoding mode
        if settings["preview"] and (settings["inputVideo"] or settings["isDashAudio"]):
            audio_filter += f'atrim={mp["start"]}:{mp["end"]},atempo={mp["speed"]}'
        # encoding mode starts each clip at time 0
        elif not settings["preview"]:
            audio_filter += f'atrim=0:{mp["duration"]},atempo={mp["speed"]}'
        # when streaming the required chunks from the internet the video and audio inputs are separate
        else:
            mps["audio"] = False
            logger.warning(
                'Audio disabled when previewing without an input video over non-dash protocol.')

    if not mps["inputVideo"] and not settings["isDashVideo"]:
        inputs += reconnectFlags

    if mps["inputVideo"]:
        inputs += f' -ss {mp["start"]} -i "{mps["inputVideo"]}" '
    else:
        inputs += f' -ss {mp["start"]} -i "{mps["videoURL"]}" '

    ffmpegCommand = ' '.join((
        ffmpegPath,
        f'-hide_banner',
        inputs,
        f'-benchmark',
        f'-c:v libvpx-vp9 -pix_fmt yuv420p',
        f'-c:a libopus -b:a 128k',
        f'-slices 8 -row-mt 1 -tile-columns 6 -tile-rows 2',
        f'-crf {mps["crf"]} -b:v {mps["autoTargetMaxBitrate"]}k',
        f'-metadata title="{mps["videoTitle"]}"',
        f'-r ({mps["r_frame_rate"]}*{mp["speed"]})' if not mp["isVariableSpeed"] and mp["speed"] > 1 else '',
        f'-af {audio_filter}' if mps["audio"] else '-an',
        f'-f webm ',
    ))

    if not mps["preview"]:
        video_filter += f'trim=0:{mp["duration"]}'
    else:
        video_filter += f'trim={mp["start"]}:{mp["end"]}'

    if mps["preview"] and not settings["inputVideo"]:
        video_filter += f',loop=loop=-1:size=(32767)'

    crops = mp["cropComponents"]
    video_filter += f',crop=x={crops[0]}:y={crops[1]}:w={crops[2]}:h={crops[3]}'
    if mps["preview"]:
        video_filter += f',scale=w=iw/2:h=ih/2'
        crops[2] /= 2
        crops[3] /= 2

    if mps["rotate"]:
        video_filter += f',transpose={mps["rotate"]}'
        crops[2], crops[3] = crops[3], crops[2]

    if mps["preview"]:
        video_filter_before_correction = video_filter

    if 0 <= mps["gamma"] <= 4 and mps["gamma"] != 1:
        video_filter += f',lutyuv=y=gammaval({mps["gamma"]})'
    if mps["extraVideoFilters"]:
        video_filter += f',{mps["extraVideoFilters"]}'
    if mps["deinterlace"]:
        video_filter += f',bwdif'
    if mps["expandColorRange"]:
        video_filter += f',colorspace=all={settings["color_space"] if settings["color_space"] else "bt709"}:range=pc'
    if mps["denoise"]["enabled"]:
        video_filter += f',hqdn3d=luma_spatial={mps["denoise"]["lumaSpatial"]}'
    # if mps["overlayPath"]:
    #     video_filter += f'[1:v]overlay=x=W-w-10:y=10:alpha=0.5'
    #     inputs += f'-i "{mps["overlayPath"]}"'

    if mps["loop"] != 'fwrev':
        video_filter += f',{mp["speedFilter"]}'
    if mps["loop"] == 'fwrev':
        reverseSpeedMap = [{"x": speedPoint["x"], "y":speedPointRev["y"]}
                           for speedPoint, speedPointRev in zip(mp["speedMap"], reversed(mp["speedMap"]))]
        reverseSpeedFilter, _ = getSpeedFilterAndDuration(
            reverseSpeedMap, mps, mps["r_frame_rate"])
        loop_filter = ''
        loop_filter += f',split=2[f1][f2];'
        loop_filter += f'[f1]{mp["speedFilter"]}[f];'
        loop_filter += f'''[f2]{reverseSpeedFilter},select='gt(n,0)',reverse,select='gt(n,0)',setpts=(PTS-STARTPTS)[r];'''
        loop_filter += f'[f][r]concat=n=2'
    if mps["loop"] == 'fade':
        dur = mp["outputDuration"]
        fadeDur = mps["fadeDuration"] = max(
            0.1, min(mps["fadeDuration"], 0.4*mp["outputDuration"]))

        easeA = f'1'
        easeB = f'0'
        easeP = f'(T/{fadeDur})'
        alphaEase = getEasingExpression('easeInOutCubic', easeA, easeB, easeP)

        loop_filter = ''
        loop_filter += f''',split=3[1][2][3];'''
        loop_filter += f'''[1]select='lte(t,{fadeDur})',setpts=(PTS-STARTPTS)[fi];'''
        loop_filter += f'''[2]select='gt(t,{fadeDur})*lt(t,{dur}-{fadeDur})',setpts=(PTS-STARTPTS)[m];'''
        loop_filter += f'''[3]select='gte(t,{dur}-{fadeDur})',setpts=(PTS-STARTPTS)[3b];'''
        loop_filter += f'''[3b]format=yuva420p,geq=lum='p(X,Y)':a='{alphaEase}*alpha(X,Y)'[fo];'''
        loop_filter += f'''[fi][fo]overlay=eof_action=pass,setpts=(PTS-STARTPTS)[cf];'''
        loop_filter += f'''[m][cf]concat=n=2'''

    if mps["preview"]:
        return runffplayCommand(inputs, video_filter, video_filter_before_correction, audio_filter, markerPairIndex, mp, mps)

    vidstabEnabled = mps["videoStabilization"]["enabled"]
    if vidstabEnabled:
        vidstab = mps["videoStabilization"]
        shakyPath = f'{webmsPath}/shaky'
        os.makedirs(shakyPath, exist_ok=True)
        transformPath = f'{shakyPath}/{mp["fileNameStem"]}.trf'
        shakyWebmPath = f'{shakyPath}/{mp["fileNameStem"]}-shaky.webm'
        video_filter += '[shaky];[shaky]'
        vidstabdetectFilter = video_filter + \
            f'''vidstabdetect=result='{transformPath}':shakiness={vidstab["shakiness"]}'''

        vidstabtransformFilter = video_filter + \
            f'''vidstabtransform=input='{transformPath}':smoothing={vidstab["smoothing"]}'''
        if mps["videoStabilizationDynamicZoom"]:
            vidstabtransformFilter += f':optzoom=2:zoomspeed={vidstab["zoomspeed"]}'
        vidstabtransformFilter += r',unsharp=5:5:0.8:3:3:0.4'

        if mps["loop"] != 'none':
            vidstabdetectFilter += loop_filter
            vidstabtransformFilter += loop_filter

        ffmpegVidstabdetect = ffmpegCommand + f'-vf "{vidstabdetectFilter}" '
        ffmpegVidstabdetect += f' -y '
        ffmpegVidstabtransform = ffmpegCommand + \
            f'-vf "{vidstabtransformFilter}" '
        ffmpegVidstabtransform += f' -n '
    else:
        ffmpegCommand += f' -n '

    ffmpegCommands = []
    if mps["twoPass"] and not vidstabEnabled:
        if mps["loop"] != 'none':
            video_filter += loop_filter
        ffmpegCommand += f' -vf "{video_filter}" '
        ffmpegPass1 = ffmpegCommand + ' -pass 1 -'
        ffmpegPass2 = ffmpegCommand + \
            f' -speed {mps["encodeSpeed"]} -pass 2 "{mp["filePath"]}"'

        ffmpegCommands = [ffmpegPass1, ffmpegPass2]
    elif vidstabEnabled:
        if mps["twoPass"]:
            ffmpegVidstabdetect += f' -pass 1'
        else:
            ffmpegVidstabdetect += f' -speed 5'
        ffmpegVidstabdetect += f' "{shakyWebmPath}"'

        if mps["twoPass"]:
            ffmpegVidstabtransform += f' -pass 2'
        ffmpegVidstabtransform += f' -speed {mps["encodeSpeed"]} "{mp["filePath"]}"'

        ffmpegCommands = [ffmpegVidstabdetect, ffmpegVidstabtransform]
    else:
        if mps["loop"] != 'none':
            video_filter += loop_filter
        ffmpegCommand += f' -vf "{video_filter}" '
        ffmpegCommand += f' -speed {mps["encodeSpeed"]} "{mp["filePath"]}"'

        ffmpegCommands = [ffmpegCommand]

    if not (1 <= len(ffmpegCommands) <= 2):
        logger.error(f'ffmpeg command could not be built.\n')
        logger.error(f'Failed to generate: "{mp["fileName"]}"\n')
        return {**(settings["markerPairs"][markerPairIndex])}

    return runffmpegCommand(ffmpegCommands, markerPairIndex, mp)


def runffmpegCommand(ffmpegCommands, markerPairIndex, mp):
    ffmpegPass1 = ffmpegCommands[0]
    if len(ffmpegCommands) == 2:
        logger.info('Running first pass...')

    logger.info('Using ffmpeg command: ' +
                re.sub(r'(&a?itags?.*?")', r'"', ffmpegPass1) + '\n')
    ffmpegProcess = subprocess.run(shlex.split(ffmpegPass1))

    if len(ffmpegCommands) == 2:
        ffmpegPass2 = ffmpegCommands[1]

        logger.info('Running second pass...')
        logger.info('Using ffmpeg command: ' +
                    re.sub(r'(&a?itags?.*?")', r'"', ffmpegPass2) + '\n')
        ffmpegProcess = subprocess.run(shlex.split(ffmpegPass2))

    if ffmpegProcess.returncode == 0:
        logger.info(f'Successfuly generated: "{mp["fileName"]}"\n')
        return {**(settings["markerPairs"][markerPairIndex]), **mp}
    else:
        logger.error(f'Failed to generate: "{mp["fileName"]}"\n')
        return {**(settings["markerPairs"][markerPairIndex])}


def getSpeedFilterAndDuration(speedMap, mps, fps):
    logger.info('-' * 80)
    video_filter_speed_map = ''
    setpts = ''
    outputDuration = 0

    fps = Fraction(fps)
    frameDur = 1 / fps
    nSects = len(speedMap) - 1
    # Account for marker pair start time as trim filter sets start time to ~0
    speedMapStartTime = speedMap[0]["x"]
    # Account for first input frame delay due to potentially imprecise trim
    startt = ceil(speedMapStartTime/frameDur) * frameDur - speedMapStartTime
    logger.info(f'First Input Frame Time: {startt}')

    for sect, (left, right) in enumerate(zip(speedMap[:-1], speedMap[1:])):
        startSpeed = left["y"]
        endSpeed = right["y"]
        speedChange = endSpeed - startSpeed

        sectStart = left["x"] - speedMapStartTime - startt
        sectEnd = right["x"] - speedMapStartTime - startt
        # Account for last input frame delay due to potentially imprecise trim
        if sect == nSects - 1:
            logger.info(
                f'Last Input Frame Time: {right["x"] - speedMapStartTime - startt}')
            sectEnd = floor(right["x"]/frameDur) * frameDur
            # When trim is frame-precise, the frame that begins at the marker pair end time is not included
            if right["x"] - sectEnd < 1e-10:
                sectEnd = sectEnd - frameDur
            sectEnd = sectEnd - speedMapStartTime - startt
            sectEnd = floor(sectEnd*1000000) / 1000000
            logger.info(f'Last Input Frame Time (Rounded): {sectEnd}')

        sectDuration = sectEnd - sectStart
        if sectDuration == 0:
            continue

        m = speedChange / sectDuration
        b = startSpeed - m * sectStart

        if speedChange == 0:
            # Duration is time multiplied by slowdown (or time divided by speed)
            sliceDuration = f'(min((T-STARTT-{sectStart}),{sectDuration})/{endSpeed})'
            outputDuration += sectDuration/endSpeed
        else:
            # Integrate the reciprocal of the linear time vs speed function for the current section
            sliceDuration = f'(1/{m})*(log(abs({m}*min((T-STARTT),{sectEnd})+{b}))-log(abs({m}*{sectStart}+{b})))'
            outputDuration += (1/m) * (log(abs(m * sectEnd
                                               + b)) - log(abs(m*sectStart + b)))
        sliceDuration = f'if(gte((T-STARTT),{sectStart}), {sliceDuration},0)'

        if sect == 0:
            setpts += f'(if(eq(N,0),0,{sliceDuration}))'
        else:
            setpts += f'+({sliceDuration})'

    video_filter_speed_map += f'''setpts='({setpts})/TB' '''

    logger.info(f'Last Output Frame Time: {outputDuration}')
    # Each output frame time is rounded to the nearest multiple of a frame's duration at the given fps
    outputDuration = round(outputDuration/frameDur)*frameDur
    # The last included frame is held for a single frame's duration
    outputDuration += frameDur
    outputDuration = round(outputDuration*1000) / 1000

    return video_filter_speed_map, outputDuration


def getEasingExpression(easingFunc, easeA, easeB, easeP):
    easeT = f'(2*{easeP})'
    easeM = f'({easeP}-1)'

    ease = '1'  # linear ease by default
    if easingFunc == 'easeInOutCubic':
        ease = f'if(lt({easeT},1), {easeP}*{easeT}^2, 1+({easeM}^3)*4)'
    if easingFunc == 'easeInOutSine':
        ease = f'0.5*(1-cos({easeP}*PI))'
    if easingFunc == 'easeOutCircle':
        ease = f'sqrt(1-{easeM}^2)'

    easingExpression = f'({easeA}+({easeB}-{easeA})*{ease})'
    return easingExpression


def runffplayCommand(inputs, video_filter, video_filter_before_correction, audio_filter, markerPairIndex, mp, mps):
    logger.info('running ffplay command')
    if 0 <= markerPairIndex < len(settings["markerPairs"]):
        ffplayOptions = f'-hide_banner -fs -sync video -fast -genpts -infbuf '
        ffplayVideoFilter = f'-vf "{video_filter}"'
        if settings["inputVideo"]:
            ffplayOptions += f' -loop 0'
            ffplayVideoFilter += f' -vf "{video_filter_before_correction}"'

        ffplayAudioFilter = f'-af {audio_filter}'

        ffplayCommand = ' '.join((
            ffplayPath,
            inputs,
            ffplayOptions,
            ffplayVideoFilter,
            ffplayAudioFilter if mps["audio"] else '-an'
        ))

        logger.info('Using ffplay command: ' +
                    re.sub(r'(&a?itags?.*?")', r'"', ffplayCommand) + '\n')
        ffplayProcess = subprocess.run(shlex.split(ffplayCommand))


class MissingMergeInput(Exception):
    pass


class MissingMarkerPairFilePath(Exception):
    pass


def makeMergedClips(settings):
    markerPairMergeList = settings["markerPairMergeList"]
    markerPairMergeList = markerPairMergeList.split(';')
    inputsTxtPath = ''

    mergeListGen = createMergeList(markerPairMergeList)
    for merge, mergeList in mergeListGen:
        inputs = ''
        logger.info('-' * 80)
        try:
            for i in mergeList:
                markerPair = settings["markerPairs"][i-1]
                if 'fileName' in markerPair and 'filePath' in markerPair:
                    if Path(markerPair["filePath"]).is_file():
                        inputs += f'''file '{settings["markerPairs"][i-1]["fileName"]}'\n'''
                    else:
                        raise MissingMergeInput
                else:
                    raise MissingMarkerPairFilePath
        except IndexError:
            logger.error(
                f'Aborting generation of webm with merge list {mergeList}.')
            logger.error(f'Missing required marker pair number {i}.')
            continue
        except MissingMergeInput:
            logger.error(
                f'Aborting generation of webm with merge list {mergeList}.')
            logger.error(
                f'Missing required input webm with path {markerPair["filePath"]}.')
            continue
        except MissingMarkerPairFilePath:
            logger.error(
                f'Aborting generation of webm with merge list {mergeList}')
            logger.error(f'Missing file path for marker pair {i}')
            continue

        inputsTxtPath = f'{webmsPath}/inputs.txt'
        with open(inputsTxtPath, "w+", encoding='utf-8') as inputsTxt:
            inputsTxt.write(inputs)
        mergedFileName = f'{settings["titleSuffix"]}-({merge}).webm'
        mergedFilePath = f'{webmsPath}/{mergedFileName}'
        ffmpegConcatCmd = f' "{ffmpegPath}" -n -hide_banner -f concat -safe 0 -i "{inputsTxtPath}" -c copy "{mergedFilePath}"'

        if not Path(mergedFilePath).is_file():
            logger.info('-' * 80)
            logger.info(f'Generating "{mergedFileName}"...\n')
            logger.info(f'Using ffmpeg command: {ffmpegConcatCmd}')
            ffmpegProcess = subprocess.run(shlex.split(ffmpegConcatCmd))
            if ffmpegProcess.returncode == 0:
                logger.info(f'Successfuly generated: "{mergedFileName}"\n')
            else:
                logger.info(f'Failed to generate: "{mergedFileName}"\n')
        else:
            logger.info(f'Skipped existing file: "{mergedFileName}"\n')

        try:
            os.remove(inputsTxtPath)
        except (OSError, FileNotFoundError):
            pass


def checkWebmExists(fileName, filePath):
    if not Path(filePath).is_file():
        logger.info(f'Generating "{fileName}"...\n')
        return False
    else:
        logger.info(f'Skipped existing file: "{fileName}"\n')
        return True


def createMergeList(markerPairMergeList):
    for merge in markerPairMergeList:
        mergeCSV = merge.split(',')
        mergeList = []
        for mergeRange in mergeCSV:
            if '-' in mergeRange:
                mergeRange = mergeRange.split('-')
                startPair = int(mergeRange[0])
                endPair = int(mergeRange[1])
                if (startPair <= endPair):
                    for i in range(startPair, endPair + 1):
                        mergeList.append(i)
                else:
                    for i in range(startPair, endPair - 1 if endPair >= 1 else 0, -1):
                        mergeList.append(i)
            else:
                mergeList.append(int(mergeRange))
        yield merge, mergeList


def ffprobeVideoProperties(video):
    try:
        ffprobeCommand = f'"{ffprobePath}" "{video}" -v quiet -select_streams v -print_format json -show_streams -show_format'
        ffprobeOutput = subprocess.check_output(shlex.split(ffprobeCommand))
    except subprocess.CalledProcessError as cpe:
        logger.error(f'Could not fetch video properties with ffprobe')
        logger.error(f'{cpe}')
        return None

    ffprobeOutput = ffprobeOutput.decode('utf-8')
    logger.info('-' * 80)
    logger.info('Detecting video properties with ffprobe')
    ffprobeData = json.loads(ffprobeOutput)

    ffprobeData["streams"][0]["bit_rate"] = int(
        int(ffprobeData["format"]["bit_rate"]) / 1000)
    return ffprobeData["streams"][0]


def autoSetCropMultiples(settings):
    cropMultipleX = (settings["width"] / settings["cropResWidth"])
    cropMultipleY = (settings["height"] / settings["cropResHeight"])
    if settings["cropResWidth"] != settings["width"] or settings["cropResHeight"] != settings["height"]:
        logger.info('-' * 80)
        logger.warning('Crop resolution does not match video resolution.')
        if settings["cropResWidth"] != settings["width"]:
            logger.warning(
                f'Crop resolution width ({settings["cropResWidth"]}) not equal to video width ({settings["width"]})')
        if settings["cropResHeight"] != settings["height"]:
            logger.warning(
                f'Crop resolution height ({settings["cropResHeight"]}) not equal to video height ({settings["height"]})')
        logger.info(
            f'Crop X offset and width will be multiplied by {cropMultipleX}')
        logger.info(
            f'Crop Y offset and height will be multiplied by {cropMultipleY}')
        if not settings["noAutoScaleCropRes"]:
            return {**settings, 'cropMultipleX': cropMultipleX, 'cropMultipleY': cropMultipleY}
        else:
            logger.info(f'Auto scale crop resolution disabled in settings.')
            return settings
    else:
        return settings


def filterDash(dashManifestUrl, dashFormatIDs):
    from xml.dom import minidom
    from urllib import request

    with request.urlopen(dashManifestUrl) as dash:
        dashdom = minidom.parse(dash)

    reps = dashdom.getElementsByTagName('Representation')
    for rep in reps:
        id = rep.getAttribute('id')
        if id not in dashFormatIDs:
            rep.parentNode.removeChild(rep)

    filteredDashPath = f'{webmsPath}/filtered-dash.xml'
    with open(filteredDashPath, 'w+', encoding='utf-8') as filteredDash:
        filteredDash.write(dashdom.toxml())

    return filteredDashPath


def getDefaultEncodeSettings(videobr):
    if videobr is None:
        encodeSettings = {'crf': 30, 'autoTargetMaxBitrate': 0,
                          'encodeSpeed': 2, 'twoPass': False}
    elif videobr <= 4000:
        encodeSettings = {'crf': 20, 'autoTargetMaxBitrate': int(
            1.6 * videobr), 'encodeSpeed': 2, 'twoPass': False}
    elif videobr <= 6000:
        encodeSettings = {'crf': 22, 'autoTargetMaxBitrate': int(
            1.5 * videobr), 'encodeSpeed': 3, 'twoPass': False}
    elif videobr <= 10000:
        encodeSettings = {'crf': 24, 'autoTargetMaxBitrate': int(
            1.4 * videobr), 'encodeSpeed': 4, 'twoPass': False}
    elif videobr <= 15000:
        encodeSettings = {'crf': 26, 'autoTargetMaxBitrate': int(
            1.3 * videobr), 'encodeSpeed': 5, 'twoPass': False}
    elif videobr <= 20000:
        encodeSettings = {'crf': 30, 'autoTargetMaxBitrate': int(
            1.2 * videobr), 'encodeSpeed': 5, 'twoPass': False}
    else:
        encodeSettings = {'crf': 35, 'autoTargetMaxBitrate': int(
            1.1 * videobr), 'encodeSpeed': 5, 'twoPass': False}
    return encodeSettings


def uploadToGfycat(settings):
    # auto gfycat uploading
    if (settings["gfycat"]):
        import urllib3
        import json
        from urllib.parse import urlencode
        http = urllib3.PoolManager()

        for outPath in outPaths:
            with open(outPath, 'rb', encoding='utf-8') as fp:
                file_data = fp.read()
            encoded_args = urlencode({'title': f'{outPath}'})
            url = UPLOAD_KEY_REQUEST_ENDPOINT + encoded_args
            r_key = http.request('POST', url)
            print(r_key.status)
            gfyname = json.loads(r_key.data.decode('utf-8'))["gfyname"]
            links.append(f'https://gfycat.com/{gfyname}')
            print(gfyname)
            fields = {'key': gfyname, 'file': (
                gfyname, file_data, 'multipart/formdata')}
            r_upload = http.request(
                'POST', FILE_UPLOAD_ENDPOINT, fields=fields)
            print(r_upload.status)
            print(r_upload.data)

        for fileName, link in zip(fileNames, links):
            markdown += f'({fileName})[{link}]\n\n'
            print('\n==Reddit Markdown==')
            print(markdown)


def cleanFileName(fileName):
    if sys.platform == 'win32':
        fileName = re.sub(r'[*?"<>\0]', '',  fileName)
        fileName = re.sub(r'[/|\\:]', '_',  fileName)
    elif sys.platform == 'darwin':
        fileName = re.sub(r'[:\0]', '_',  fileName)
    elif sys.platform.startswith('linux'):
        fileName = re.sub(r'[/\0]', '_',  fileName)
    return fileName


def getVidstabPreset(level, videoStabilizationDynamicZoom):
    vidstabPreset = {"enabled": False, "desc": "Disabled"}
    if level == 1:
        vidstabPreset = {"enabled": True, "shakiness": 2,
                         "zoomspeed": 0.05, "smoothing": 2, "desc": "Very Weak"}
    elif level == 2:
        vidstabPreset = {"enabled": True, "shakiness": 4,
                         "zoomspeed": 0.1, "smoothing": 4,  "desc": "Weak"}
    elif level == 3:
        vidstabPreset = {"enabled": True, "shakiness": 6,
                         "zoomspeed": 0.2, "smoothing": 6,   "desc": "Medium"}
    elif level == 4:
        vidstabPreset = {"enabled": True, "shakiness": 8,
                         "zoomspeed": 0.3,  "smoothing": 10, "desc": "Strong"}
    elif level == 5:
        vidstabPreset = {"enabled": True, "shakiness": 10,
                         "zoomspeed": 0.4, "smoothing": 16,  "desc": "Very Strong"}
    elif level == 6:
        vidstabPreset = {"enabled": True, "shakiness": 10,
                         "zoomspeed": 0.5, "smoothing": 22,  "desc": "Strongest"}
    return vidstabPreset


def getDenoisePreset(level):
    denoisePreset = {"enabled": False, "desc": "Disabled"}
    if level == 1:
        denoisePreset = {"enabled": True,
                         "lumaSpatial": 1, "desc": "Very Weak"}
    elif level == 2:
        denoisePreset = {"enabled": True, "lumaSpatial": 2,  "desc": "Weak"}
    elif level == 3:
        denoisePreset = {"enabled": True, "lumaSpatial": 4,  "desc": "Medium"}
    elif level == 4:
        denoisePreset = {"enabled": True, "lumaSpatial": 6,  "desc": "Strong"}
    elif level == 5:
        denoisePreset = {"enabled": True,
                         "lumaSpatial": 8,  "desc": "Very Strong"}
    return denoisePreset


main()
