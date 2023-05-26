import boto3

i_str = "화장실 수도가 틀려있습니다. 수도를 잠궈주세요"

polly_client = boto3.Session(
                aws_access_key_id="AKIAZBVLWGQ3N7R5UW6V",
    aws_secret_access_key="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",
    region_name='ap-northeast-2').client('polly')

response = polly_client.synthesize_speech(VoiceId='Seoyeon',
                OutputFormat='mp3',
                Text = i_str)

file = open('3.mp3','wb')
file.write(response['AudioStream'].read())
