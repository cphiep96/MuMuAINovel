def test_omnivoice_reuses_first_synthetic_voice_for_next_scene(monkeypatch):
    import numpy as np
    from app.services.video_export import tts
    calls=[]
    anchor=object()
    class Model:
        def generate(self,**kwargs):
            calls.append(kwargs)
            return [np.ones(24000,dtype=np.float32)]
        def create_voice_clone_prompt(self,**kwargs):
            assert kwargs['ref_text']=='An trở về.'
            return anchor
    monkeypatch.setattr(tts,'_load_omnivoice_model',lambda:Model())
    engine=tts.OmniVoiceTTSEngine(model='female')
    engine._generate_sync('An trở về.')
    engine._generate_sync('Lâm tiếp tục chèo đò.')
    assert 'instruct' in calls[0]
    assert calls[1]['voice_clone_prompt'] is anchor
    assert 'instruct' not in calls[1]
