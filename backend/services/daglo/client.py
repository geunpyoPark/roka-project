import argparse
import grpc
from backend.services.daglo import speech_pb2, speech_pb2_grpc
import pyaudio
import sys

# 오디오 스트림 설정
SAMPLE_RATE = 16000
CHUNK = int(SAMPLE_RATE * 0.25) # 0.25초에 해당하는 프레임
CHANNELS = 1
FORMAT = pyaudio.paInt16

def generate_requests(audio_stream, language_code='ko-KR', interim_results=True):
    """
    마이크 스트림에서 오디오 데이터를 읽어 스트리밍 요청을 생성하는 제너레이터 함수.
    """
    # 첫 번째 요청: 설정(Config) 전송
    config = speech_pb2.RecognitionConfig(
        language_code=language_code,
        interim_results=interim_results
    )
    yield speech_pb2.StreamingRecognizeRequest(config=config)

    # 이후 요청: 오디오 데이터 전송
    while True:
        try:
            # 오디오 스트림에서 데이터 읽기
            audio_chunk = audio_stream.read(CHUNK)
            if not audio_chunk:
                break
            yield speech_pb2.StreamingRecognizeRequest(audio_content=audio_chunk)
        except IOError as e:
            print(f"Error reading from audio stream: {e}", file=sys.stderr)
            break
            
    # 마지막 요청: 끝(EOS)을 나타내기 위해 빈 메시지를 전송
    yield speech_pb2.StreamingRecognizeRequest()

def run_streaming_recognition_from_mic(server_address, api_token):
    """
    마이크 입력을 사용하여 실시간 스트리밍 음성 인식을 실행하는 메인 함수.
    """
    # gRPC 채널 및 스텁 설정
    creds = grpc.ssl_channel_credentials()
    channel = grpc.secure_channel(server_address, creds)
    stub = speech_pb2_grpc.SpeechStub(channel)

    # API 인증을 위한 메타데이터(헤더)
    metadata = (
         ("authorization", f"Bearer {api_token}"),
    )

    # PyAudio 인스턴스 초기화
    audio = pyaudio.PyAudio()

    # 오디오 스트림 열기
    try:
        stream = audio.open(format=FORMAT,
                            channels=CHANNELS,
                            rate=SAMPLE_RATE,
                            input=True,
                            frames_per_buffer=CHUNK)

        print("마이크 녹음 및 스트리밍 시작. 'Ctrl+C'를 눌러 종료하세요.")
        
        # 요청과 응답을 양방향 스트리밍
        response_iterator = stub.StreamingRecognize(
            generate_requests(stream),
            metadata=metadata
        )
        
        # 응답을 처리하는 루프
        for response in response_iterator:
            if response.result:
                if response.result.is_final:
                    print(f"최종 결과: {response.result.transcript}")
                else:
                    print(f"부분 결과: {response.result.transcript}", end='\r')

    except grpc.RpcError as e:
        print(f"\ngRPC 오류 발생: {e.code()}, {e.details()}", file=sys.stderr)
    except KeyboardInterrupt:
        print("\n녹음을 중단하고 프로그램을 종료합니다.")
    finally:
        # 스트림 및 PyAudio 객체 정리
        if 'stream' in locals() and stream.is_active():
            stream.stop_stream()
            stream.close()
        audio.terminate()
        channel.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="gRPC Speech Recognition Client")
    parser.add_argument(
        "--server",
        type=str,
        required=True,
        help="gRPC server address (e.g., apis.daglo.ai)",
    )
    parser.add_argument("--token", type=str, required=True, help="API Token")

    args = parser.parse_args()
    run_streaming_recognition_from_mic(args.server, args.token)